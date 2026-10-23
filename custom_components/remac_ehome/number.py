"""Number helper: lifetime of the next temporary passcode."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RemacConfigEntry
from .const import DOMAIN
from .coordinator import RemacCoordinator
from .entity import RemacEntity

MIN_MINUTES = 1
MAX_MINUTES = 30
DEFAULT_MINUTES = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RemacConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the duration helper."""
    async_add_entities([RemacTempDuration(entry)])


class RemacTempDuration(RemacEntity, NumberEntity, RestoreEntity):
    """Passcode lifetime in minutes.

    The cloud accepts 60–1800 seconds and the vendor app exposes 1–30 minutes in
    one minute steps, so this mirrors that exactly.
    """

    _attr_name = "Temporary passcode duration"
    _attr_translation_key = "temp_duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = MIN_MINUTES
    _attr_native_max_value = MAX_MINUTES
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, entry: RemacConfigEntry) -> None:
        coordinator: RemacCoordinator = entry.runtime_data["coordinator"]
        super().__init__(coordinator, "temp_minutes")
        self._entry_id = entry.entry_id
        self._attr_native_value = DEFAULT_MINUTES

    def _store(self) -> dict:
        return self.hass.data[DOMAIN][self._entry_id].setdefault(
            "temp", {"user": "访客", "minutes": DEFAULT_MINUTES}
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last value and publish it to the shared cache."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                self._attr_native_value = min(
                    MAX_MINUTES, max(MIN_MINUTES, float(last_state.state))
                )
            except (TypeError, ValueError):
                pass
        self._store()["minutes"] = int(self._attr_native_value or DEFAULT_MINUTES)

    async def async_set_native_value(self, value: float) -> None:
        """Store the new duration."""
        self._attr_native_value = value
        self._store()["minutes"] = int(value)
        self.async_write_ha_state()
