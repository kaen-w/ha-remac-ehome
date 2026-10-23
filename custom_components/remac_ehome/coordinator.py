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
from .decoder import decode_record
from .exceptions import RemacAuthError, RemacConnectionError, RemacCredentialsError

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
        self._status: dict[str, Any] = {}
        self._seen: set[str] = set()
        self._primed = False
        self._tick = 0

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
    def user_map(self) -> dict[str, str]:
        """``userNo`` → human readable credential label."""
        return {
            str(user.get("userNo")): str(
                user.get("userName") or user.get("typeName") or user.get("userNo")
            )
            for user in self.lock_users
            if user.get("userNo") is not None
        }

    # ----------------------------------------------------------------- update
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

            self._logs = await self.api.async_get_logs(self.dev_code, page_size=20)
            self._tick += 1
            self._emit_new_records(self._logs)
        except RemacCredentialsError as err:
            # Wrong phone/password -> ask the user, HA shows the reauth dialog.
            raise ConfigEntryAuthFailed(str(err)) from err
        except RemacAuthError as err:
            # Token rejected and we are waiting out the backoff before logging in
            # again. Not a user problem: keep retrying quietly.
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
