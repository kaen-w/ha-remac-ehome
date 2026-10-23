"""The REMAC (云邻 e家) integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import RemacApi
from .const import (
    CONF_DEVICE_ID,
    CONF_HOUSE_ID,
    CONF_MOBILE,
    CONF_PASSWORD,
    CONF_TOKEN,
    DEFAULT_DEVICE_ID,
    DEFAULT_HOUSE_ID,
    DOMAIN,
    SERVICE_TEMP_PASSWORD,
)
from .coordinator import RemacCoordinator
from .services import async_generate_temp_password

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.TEXT,
]

RemacConfigEntry = ConfigEntry[dict[str, Any]]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

TEMP_PASSWORD_SCHEMA = vol.Schema(
    {
        vol.Required("username"): cv.string,
        vol.Optional("expire", default=1800): vol.All(
            cv.positive_int, vol.Range(min=60, max=1800)
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RemacConfigEntry) -> bool:
    """Set up REMAC from a config entry."""
    api = RemacApi(
        async_get_clientsession(hass),
        device_id=entry.data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
        token=entry.data.get(CONF_TOKEN),
        mobile=entry.data.get(CONF_MOBILE),
        password=entry.data.get(CONF_PASSWORD),
    )
    coordinator = RemacCoordinator(
        hass,
        api,
        house_id=entry.data.get(CONF_HOUSE_ID, DEFAULT_HOUSE_ID),
        name=entry.title,
        entry_id=entry.entry_id,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "temp": {"user": "访客", "minutes": 30},
        "last_passcode": None,
    }
    entry.runtime_data = hass.data[DOMAIN][entry.entry_id]

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _handle_temp_password(call: ServiceCall) -> None:
        await async_generate_temp_password(hass, entry, call)

    if not hass.services.has_service(DOMAIN, SERVICE_TEMP_PASSWORD):
        hass.services.async_register(
            DOMAIN,
            SERVICE_TEMP_PASSWORD,
            _handle_temp_password,
            schema=TEMP_PASSWORD_SCHEMA,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RemacConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_TEMP_PASSWORD)
    return True
