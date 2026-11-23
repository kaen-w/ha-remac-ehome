"""Door lock platform."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RemacConfigEntry
from .coordinator import RemacCoordinator
from .entity import RemacEntity

#: ``doorState`` reported by the lock.
DOOR_CLOSED = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemacConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the door lock entity."""
    async_add_entities([RemacDoorLock(entry.runtime_data["coordinator"])])


class RemacDoorLock(RemacEntity, LockEntity):
    """Read-only door lock state.

    Remote unlocking is deliberately not implemented: this lock family exposes
    credential management (fingerprints, passcodes, temporary passcodes) rather
    than remote opening.
    """

    _attr_name = None
    _attr_icon = "mdi:door-closed-lock"

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "lock")

    @property
    def is_locked(self) -> bool | None:
        state = self._status.get("doorState")
        if state is None:
            return None
        return state == DOOR_CLOSED

    @property
    def available(self) -> bool:
        return super().available and bool(self._status)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status
        return {
            "dev_code": self.coordinator.dev_code,
            "gateway": (self.coordinator.lock_dev.get("master") or {}).get("devName"),
            "gateway_code": self.coordinator.master_code,
            "battery_percent": status.get("batteryRemaining"),
            "low_battery": status.get("lowBattery"),
            "online": status.get("onlineStatus"),
            "guard": status.get("guard"),
            "outside_open": status.get("outsideOpen"),
            "open_record": status.get("openRecord"),
            "lock_volume_level": status.get("LockVolumeLevel"),
            "last_status_update": status.get("lastStatusUpdate"),
            "credentials": self.coordinator.lock_users,
        }

    async def async_lock(self, **kwargs: Any) -> None:
        """Not supported by this lock family."""
        raise HomeAssistantError(
            translation_domain="remac_ehome",
            translation_key="remote_lock_unsupported",
        )

    async def async_unlock(self, **kwargs: Any) -> None:
        """Not supported by this lock family."""
        raise HomeAssistantError(
            translation_domain="remac_ehome",
            translation_key="remote_unlock_unsupported",
        )
