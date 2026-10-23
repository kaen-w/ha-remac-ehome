"""Diagnostics support for REMAC."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MOBILE, CONF_PASSWORD, CONF_TOKEN

TO_REDACT = {CONF_TOKEN, CONF_PASSWORD, CONF_MOBILE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    store = hass.data.get("remac_ehome", {}).get(entry.entry_id, {})
    coordinator = store.get("coordinator")
    data = {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
    }
    if coordinator is not None:
        data["coordinator"] = {
            "dev_code": coordinator.dev_code,
            "master_code": coordinator.master_code,
            "house_id": coordinator.house_id,
            "device_count": len(coordinator.devices),
            "lock_users": coordinator.lock_users,
            "last_status": coordinator.data.get("status") if coordinator.data else None,
        }
    return async_redact_data(data, TO_REDACT)
