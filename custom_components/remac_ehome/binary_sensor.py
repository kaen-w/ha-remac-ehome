"""Binary sensors for the REMAC door lock."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RemacConfigEntry
from .coordinator import RemacCoordinator
from .entity import RemacEntity

ONLINE = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemacConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: RemacCoordinator = entry.runtime_data["coordinator"]
    async_add_entities(
        [RemacOnlineSensor(coordinator), RemacLowBatterySensor(coordinator)]
    )


class RemacOnlineSensor(RemacEntity, BinarySensorEntity):
    """Cloud connectivity of the lock."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "online")

    @property
    def is_on(self) -> bool:
        return self._status.get("onlineStatus") == ONLINE


class RemacLowBatterySensor(RemacEntity, BinarySensorEntity):
    """Low battery warning reported by the lock."""

    _attr_translation_key = "low_battery"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_icon = "mdi:battery-alert"

    def __init__(self, coordinator: RemacCoordinator) -> None:
        super().__init__(coordinator, "low_battery")

    @property
    def is_on(self) -> bool:
        return bool(self._status.get("lowBattery"))
