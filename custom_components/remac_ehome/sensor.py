"""Sensors for the REMAC door lock."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RemacConfigEntry
from .const import DOMAIN, SIGNAL_TEMP_PASSCODE
from .coordinator import RemacCoordinator
from .decoder import describe_event
from .entity import RemacEntity

DOOR_STATES: dict[int, str] = {0: "open", 1: "closed"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemacConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: RemacCoordinator = entry.runtime_data["coordinator"]
    async_add_entities(
        [
            RemacBatterySensor(coordinator),
            RemacDoorStateSensor(coordinator),
            RemacActivitySensor(coordinator),
            RemacTempPasscodeSensor(hass, entry.entry_id, coordinator),
        ]
    )


class RemacBatterySensor(RemacEntity, SensorEntity):
    """Battery percentage.

    The cloud returns two battery fields:

    * ``BatteryRemaining`` is a constant 100 and must be ignored.
    * ``batteryRemaining`` is the real level (verified against the app, which
      showed "low battery" while the constant still reported 100).
    """

    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:battery"

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "battery")

    @property
    def native_value(self) -> int | None:
        real = self._status.get("batteryRemaining")
        if real is not None:
            return real
        return self._status.get("BatteryRemaining")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "low_battery": self._status.get("lowBattery"),
            "raw_battery_remaining": self._status.get("BatteryRemaining"),
        }


class RemacDoorStateSensor(RemacEntity, SensorEntity):
    """Door contact state."""

    _attr_translation_key = "door_state"
    _attr_icon = "mdi:door"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["open", "closed"]

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "door_state")

    @property
    def native_value(self) -> str | None:
        return DOOR_STATES.get(self._status.get("doorState"))


class RemacActivitySensor(RemacEntity, SensorEntity):
    """What happened last, in words, plus the recent activity history.

    The state used to be a bare timestamp, which made the activity log and the
    logbook unreadable: every line just said "最近动态 → 2026-10-27 22:07:06".
    The state is now a sentence ("指纹开锁 · 屋主") followed by the clock time,
    so two identical actions stay distinguishable and every record still lands
    in the history. The full structured record is in ``last_event``.
    """

    _attr_translation_key = "last_activity"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "activity")

    @property
    def native_value(self) -> str | None:
        event = self.coordinator.last_event
        if not event:
            return None
        text = event.get("text") or describe_event(event)
        stamp = str(event.get("time") or "")
        clock = stamp.split(" ")[-1] if " " in stamp else stamp
        return f"{text} · {clock}" if clock else text

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_event": self.coordinator.last_event,
            "last_unlock": self.coordinator.last_unlock,
            "recent": self.coordinator.recent_events(),
            "count": len(self._logs),
            "credentials": self.coordinator.lock_users,
        }


class RemacTempPasscodeSensor(RemacEntity, SensorEntity, RestoreEntity):
    """Most recently generated temporary passcode.

    The passcode is single use, so the state only shows it while it is actually
    usable. Once it has been spent (the lock logs a temporary-passcode unlock)
    or its TTL has run out, the state drops to unknown and ``status`` says why —
    leaving a dead code on the dashboard was the whole point of this fix.
    """

    _attr_translation_key = "temp_passcode"
    _attr_icon = "mdi:key-variant"

    def __init__(self, hass: HomeAssistant, entry_id: str, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "temp_passcode")
        self._hass = hass
        self._entry_id = entry_id

    @property
    def _store(self) -> dict[str, Any]:
        return self._hass.data.get(DOMAIN, {}).get(self._entry_id) or {}

    @property
    def _last(self) -> dict[str, Any]:
        return self._store.get("last_passcode") or {}

    @property
    def native_value(self) -> str | None:
        last = self._last
        if last.get("status") in ("used", "expired"):
            return None
        return last.get("passcode")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._last
        status = last.get("status") or ("active" if last.get("passcode") else None)
        attrs: dict[str, Any] = {
            "status": status,
            "username": last.get("username"),
            "expires_at": last.get("expires_at"),
            "expire_seconds": last.get("expire"),
            "generated_at": last.get("generated_at"),
        }
        if last.get("used_at"):
            attrs["used_at"] = last["used_at"]
        if last.get("expired_at"):
            attrs["expired_at"] = last["expired_at"]
        return attrs

    async def async_added_to_hass(self) -> None:
        """Restore the last passcode across restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        store = self._store
        if last_state is not None and store and not store.get("last_passcode"):
            attrs = last_state.attributes
            # Keep a spent/expired passcode spent after a restart: restore the
            # verdict too, not just the code.
            status = attrs.get("status")
            if status in ("used", "expired") or last_state.state not in (
                "unknown",
                "unavailable",
                "",
            ):
                store["last_passcode"] = {
                    "passcode": last_state.state,
                    "username": attrs.get("username"),
                    "expires_at": attrs.get("expires_at"),
                    "expire": attrs.get("expire_seconds"),
                    "generated_at": attrs.get("generated_at"),
                    "status": status,
                    "used_at": attrs.get("used_at"),
                    "expired_at": attrs.get("expired_at"),
                }
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_TEMP_PASSCODE, self.async_write_ha_state)
        )
