"""Data update coordinator for REMAC door locks."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RemacApi
from .const import (
    DOMAIN,
    EVENT_DOOR,
    DEFAULT_SCAN_INTERVAL,
    STATUS_EVERY,
    USERS_EVERY,
)
from .decoder import decode_record, describe_event
from .exceptions import (
    RemacAuthError,
    RemacConnectionError,
    RemacCredentialsError,
    RemacLoginDeferred,
)

_LOGGER = logging.getLogger(__name__)

MAX_TRACKED_RECORDS = 500


def is_lock(device: dict[str, Any]) -> bool:
    """Return True when a cloud device entry describes a door lock."""
    return (
        device.get("devCatagory") == "doorLock"
        or "doorlock" in str(device.get("modelId", "")).lower()
        or "门锁" in str(device.get("devName", ""))
    )


class RemacCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the lock and converts new activity records into bus events.

    The activity log is the fast path: it is polled every
    :data:`~custom_components.remac_ehome.const.LOG_INTERVAL` seconds and every
    unseen record is re-emitted on :data:`~.const.EVENT_DOOR`. That is what makes
    ``unlock`` automations feel instant.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: RemacApi,
        *,
        house_id: str,
        name: str,
        entry_id: str = "",
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {name}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.scan_interval = scan_interval
        self.api = api
        self.house_id = house_id
        self.entry_id = entry_id
        self.devices: list[dict[str, Any]] = []
        self.lock_dev: dict[str, Any] = {}
        self.gateway_dev: dict[str, Any] = {}
        self.lock_users: list[dict[str, Any]] = []
        self._logs: list[dict[str, Any]] = []
        self.last_event: dict[str, Any] | None = None
        self._status: dict[str, Any] = {}
        self._seen: set[str] = set()
        self._primed = False
        self._tick = 0
        self._log_failures = 0

    # ------------------------------------------------------------------ props
    @property
    def dev_code(self) -> str:
        """Device code of the door lock."""
        return self.lock_dev.get("devCode", "")

    @property
    def master_code(self) -> str:
        """Device code of the gateway the lock is paired to."""
        return (self.lock_dev.get("master") or {}).get("devCode", "")

    @property
    def user_map(self) -> dict[str, dict[str, str]]:
        """``userNo`` → human readable credential label.

        The label the user typed in the app lives in ``userRole`` (user list
        endpoint) / ``user_role`` (device ``register_users``); ``typeName`` is
        just the credential kind such as "普通指纹".
        """
        mapping: dict[str, dict[str, str]] = {}
        sources: list[dict[str, Any]] = list(self.lock_users)
        extra = (self.lock_dev.get("extraAttr") or {}).get("register_users") or []
        for row in extra:
            sources.append(
                {
                    "userNo": row.get("user_no"),
                    "userRole": row.get("user_role"),
                    "typeName": row.get("type_name"),
                }
            )
        for user in sources:
            user_no = user.get("userNo")
            if user_no is None:
                continue
            name = (
                user.get("userRole")
                or user.get("user_role")
                or user.get("userName")
                or user.get("typeName")
                or user.get("type_name")
                or str(user_no)
            )
            type_name = user.get("typeName") or user.get("type_name") or ""
            mapping.setdefault(
                str(user_no), {"name": str(name), "type": str(type_name)}
            )
        return mapping

    # ----------------------------------------------------------------- update
    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """Decoded activity records, newest first, each with a readable ``text``."""
        users = self.user_map
        events: list[dict[str, Any]] = []
        for record in self._logs[:limit]:
            event = decode_record(record.get("data"), users)
            events.append(
                {
                    "time": record.get("createTime"),
                    **event,
                    "text": describe_event(event),
                }
            )
        return events

    @property
    def last_unlock(self) -> dict[str, Any] | None:
        """Newest record that actually opened the lock, if any."""
        for event in self.recent_events():
            if event.get("type") == "unlock":
                return event
        return None

    def _track_last_event(self) -> None:
        """Remember the newest record ever seen, and only ever move forward.

        ``/device/log/list`` sometimes answers with a slightly different page, so
        the head of the list can jump backwards. A state that follows the raw
        head flickers between two timestamps and litters the logbook with
        meaningless changes, so advance monotonically instead.
        """
        if not self._logs:
            return
        record = self._logs[0]
        when = str(record.get("createTime") or "")
        if self.last_event is not None:
            previous = str(self.last_event.get("time") or "")
            if when <= previous:
                return
        event = decode_record(record.get("data"), self.user_map)
        self.last_event = {
            "time": when,
            **event,
            "text": describe_event(event),
        }

    @staticmethod
    def _newest_first(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort records newest first — ``createTime`` is ``YYYY-MM-DD HH:MM:SS``."""
        return sorted(
            logs, key=lambda row: str(row.get("createTime") or ""), reverse=True
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self.lock_dev:
                await self._async_discover()

            if self._tick % STATUS_EVERY == 0 or not self._status:
                self._status = await self.api.async_get_status(self.dev_code)

            if self._tick % USERS_EVERY == 0 or not self.lock_users:
                try:
                    self.lock_users = await self.api.async_get_lock_users(self.dev_code)
                except RemacAuthError:
                    raise
                except Exception as err:  # noqa: BLE001 - never break polling
                    _LOGGER.debug("lock user refresh failed: %s", err)

            # The activity endpoint is flaky (occasionally answers
            # "9999 智能服务未响应"). Never let it take the whole integration
            # down: keep the last known records and retry next cycle.
            try:
                self._logs = self._newest_first(
                    await self.api.async_get_logs(self.dev_code, page_size=20)
                )
            except RemacAuthError:
                raise
            except Exception as err:  # noqa: BLE001
                if not self._logs:
                    raise UpdateFailed(f"activity log unavailable: {err}") from err
                self._log_failures += 1
                if self._log_failures in (1, 10, 100):
                    _LOGGER.warning(
                        "activity log fetch failed %d time(s), keeping %d cached "
                        "record(s): %s",
                        self._log_failures,
                        len(self._logs),
                        err,
                    )
            else:
                self._log_failures = 0
                self._track_last_event()
                self._emit_new_records(self._logs)
            self._tick += 1
        except RemacCredentialsError as err:
            # Wrong phone/password -> ask the user, HA shows the reauth dialog.
            raise ConfigEntryAuthFailed(str(err)) from err
        except RemacLoginDeferred as err:
            # Inside the cool-down window: expected while the app is open.
            raise UpdateFailed(str(err), log_message=False) from err
        except RemacAuthError as err:
            # Token rejected and the next login is backed off. Not a user
            # problem: keep retrying quietly.
            raise UpdateFailed(str(err)) from err
        except RemacConnectionError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"unexpected error: {err}") from err
        return {"status": self._status, "logs": self._logs}

    async def _async_discover(self) -> None:
        self.devices = await self.api.async_get_devices(self.house_id)
        locks = [device for device in self.devices if is_lock(device)]
        if not locks:
            raise UpdateFailed("no door lock found under this house")
        self.lock_dev = locks[0]
        master_code = self.master_code
        for device in self.devices:
            if device.get("devCode") == master_code:
                self.gateway_dev = device
                break
        _LOGGER.info(
            "discovered %d device(s); lock=%s gateway=%s",
            len(self.devices),
            self.dev_code,
            master_code,
        )

    # ----------------------------------------------------------------- events
    def _emit_new_records(self, logs: list[dict[str, Any]]) -> None:
        """Fire one bus event per activity record we have not seen yet."""
        if not self._primed:
            # First poll only seeds the baseline; never replay history.
            for record in logs:
                self._seen.add(self._record_key(record))
            self._primed = True
            _LOGGER.debug("activity baseline primed with %d record(s)", len(logs))
            return

        users = self.user_map
        fresh = [record for record in logs if self._record_key(record) not in self._seen]
        for record in reversed(fresh):  # oldest first
            self._seen.add(self._record_key(record))
            event = decode_record(record.get("data"), users)
            payload = {
                "dev_code": self.dev_code,
                "device_name": self.lock_dev.get("devName"),
                "time": record.get("createTime"),
                **event,
            }
            _LOGGER.debug("door event: %s", payload)
            self.hass.bus.async_fire(EVENT_DOOR, payload)

        if len(self._seen) > MAX_TRACKED_RECORDS:
            self._seen = {self._record_key(record) for record in logs}

    @staticmethod
    def _record_key(record: dict[str, Any]) -> str:
        return f"{record.get('createTime')}|{record.get('data')}"
