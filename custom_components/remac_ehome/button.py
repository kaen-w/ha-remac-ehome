"""Button that generates a temporary door passcode."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RemacConfigEntry
from .const import DOMAIN, SERVICE_TEMP_PASSWORD
from .coordinator import RemacCoordinator
from .entity import RemacEntity

DEFAULT_MINUTES = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemacConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the temporary passcode button."""
    async_add_entities([RemacTempPasswordButton(hass, entry)])


class RemacTempPasswordButton(RemacEntity, ButtonEntity):
    """Generate a passcode using the companion number/text helpers."""

    _attr_translation_key = "generate_temp_passcode"
    _attr_icon = "mdi:key-plus"

    def __init__(self, hass: HomeAssistant, entry: RemacConfigEntry) -> None:
        coordinator: RemacCoordinator = entry.runtime_data["coordinator"]
        super().__init__(coordinator, "generate_temp_passcode")
        self._hass = hass
        self._entry = entry

    async def async_press(self) -> None:
        """Ask the cloud for a new passcode."""
        store = self._hass.data[DOMAIN][self._entry.entry_id]
        cache = store.setdefault("temp", {"user": "访客", "minutes": DEFAULT_MINUTES})
        minutes = min(30, max(1, int(cache.get("minutes") or DEFAULT_MINUTES)))
        await self._hass.services.async_call(
            DOMAIN,
            SERVICE_TEMP_PASSWORD,
            {"username": cache.get("user") or "访客", "expire": minutes * 60},
            blocking=True,
        )
