"""Shared entity base for the REMAC integration."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import RemacCoordinator


class RemacEntity(CoordinatorEntity[RemacCoordinator]):
    """Base class wiring entities to the door lock device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RemacCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.dev_code}_{key}"
        device = coordinator.lock_dev or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.dev_code)},
            name=device.get("devName") or "Door lock",
            manufacturer=MANUFACTURER,
            model=device.get("modelId"),
            sw_version=device.get("deviceVer"),
            serial_number=device.get("identifier"),
            suggested_area=(device.get("domain") or {}).get("domainName"),
            configuration_url="https://app.smartmideazy.com",
        )

    @property
    def _status(self) -> dict[str, Any]:
        """Latest status block."""
        return (self.coordinator.data or {}).get("status") or {}

    @property
    def _logs(self) -> list[dict[str, Any]]:
        """Latest activity records."""
        return (self.coordinator.data or {}).get("logs") or []
