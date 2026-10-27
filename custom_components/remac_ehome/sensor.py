"""Sensors for the REMAC door lock."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RemacConfigEntry
from .const import DOMAIN, SIGNAL_TEMP_PASSCODE
from .coordinator import RemacCoordinator
from .decoder import decode_record
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
    _attr_options = ["open", "closed"]

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "door_state")

    @property
    def native_value(self) -> str | None:
        return DOOR_STATES.get(self._status.get("doorState"))


class RemacActivitySensor(RemacEntity, SensorEntity):
    """Timestamp of the newest activity record plus the recent history."""

    _attr_translation_key = "last_activity"
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "activity")

    @property
    def native_value(self) -> str | None:
        logs = self._logs
        return logs[0].get("createTime") if logs else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        users = self.coordinator.user_map
        events = [
            {"time": record.get("createTime"), **decode_record(record.get("data"), users)}
            for record in self._logs[:10]
        ]
        return {
            "recent": events,
            "count": len(self._logs),
            "credentials": self.coordinator.lock_users,
        }


class RemacTempPasscodeSensor(RemacEntity, SensorEntity, RestoreEntity):
    """Most recently generated temporary passcode."""

    _attr_translation_key = "temp_passcode"
    _attr_icon = "mdi:key-variant"

    def __init__(
        self, hass: HomeAssistant, entry_id: str, coordinator: RemacCoordinator
    ) -> None:
        super().__init__(coordinator, "temp_passcode")
        self._hass = hass
        self._entry_id = entry_id

    @property
    def _store(self) -> dict[str, Any]:
        return self._hass.data.get(DOMAIN, {}).get(self._entry_id) or {}

    @property
    def native_value(self) -> str | None:
        return (self._store.get("last_passcode") or {}).get("passcode")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._store.get("last_passcode") or {}
        return {
            "username": last.get("username"),
            "expires_at": last.get("expires_at"),
            "expire_seconds": last.get("expire"),
            "generated_at": last.get("generated_at"),
        }

    async def async_added_to_hass(self) -> None:
        """Restore the last passcode across restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        store = self._store
        if last_state is not None and store and not store.get("last_passcode"):
            if last_state.state not in ("unknown", "unavailable", ""):
                store["last_passcode"] = {
                    "passcode": last_state.state,
                    "username": last_state.attributes.get("username"),
                    "expires_at": last_state.attributes.get("expires_at"),
                    "expire": last_state.attributes.get("expire_seconds"),
                    "generated_at": last_state.attributes.get("generated_at"),
                }
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_TEMP_PASSCODE, self.async_write_ha_state
            )
        )
