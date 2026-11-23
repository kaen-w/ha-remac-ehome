"""Text helper: who the temporary passcode is for."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RemacConfigEntry
from .const import DOMAIN
from .coordinator import RemacCoordinator
from .entity import RemacEntity

DEFAULT_USER = "访客"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemacConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the username helper."""
    async_add_entities([RemacTempUserText(entry)])


class RemacTempUserText(RemacEntity, TextEntity, RestoreEntity):
    """Label attached to the next generated passcode."""

    _attr_translation_key = "temp_user"
    _attr_icon = "mdi:account-key"
    _attr_native_min = 1
    _attr_native_max = 32
    _attr_mode = TextMode.TEXT

    def __init__(self, entry: RemacConfigEntry) -> None:
        coordinator: RemacCoordinator = entry.runtime_data["coordinator"]
        super().__init__(coordinator, "temp_user")
        self._entry_id = entry.entry_id
        self._attr_native_value = DEFAULT_USER

    def _store(self) -> dict:
        return self.hass.data[DOMAIN][self._entry_id].setdefault(
            "temp", {"user": DEFAULT_USER, "minutes": 30}
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last value and publish it to the shared cache."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
            "",
        ):
            self._attr_native_value = last_state.state
        self._store()["user"] = self._attr_native_value

    async def async_set_value(self, value: str) -> None:
        """Store the new label."""
        self._attr_native_value = value or DEFAULT_USER
        self._store()["user"] = self._attr_native_value
        self.async_write_ha_state()
