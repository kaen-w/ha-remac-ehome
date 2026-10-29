"""Service implementations for the REMAC integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_TEMP_CREATED,
    NOTIFICATION_TEMP_PASSCODE,
    SIGNAL_TEMP_PASSCODE,
)
from .exceptions import RemacError

_LOGGER = logging.getLogger(__name__)


async def async_generate_temp_password(
    hass: HomeAssistant, entry: ConfigEntry, call: ServiceCall
) -> None:
    """Generate a temporary door passcode."""
    store = hass.data[DOMAIN][entry.entry_id]
    api = store["api"]
    coordinator = store["coordinator"]

    username = call.data["username"]
    expire = int(call.data.get("expire", 1800))

    result = await api.async_generate_temp_password(
        coordinator.dev_code, coordinator.master_code, username, expire
    )
    passcode = result.get("passcode")
    if not passcode:
        raise RemacError("the cloud returned no passcode")

    expires_at = dt_util.now() + timedelta(seconds=expire)
    store["last_passcode"] = {
        "passcode": passcode,
        "username": username,
        "expire": expire,
        "expires_at": expires_at.isoformat(),
        "generated_at": dt_util.now().isoformat(),
    }
    _LOGGER.warning(
        "temporary passcode created: %s (user=%s, ttl=%ss)", passcode, username, expire
    )

    persistent_notification.async_create(
        hass,
        f"使用者：**{username}**\n\n密码：### `{passcode}`\n\n"
        f"有效期：{expire // 60} 分钟（至 {expires_at.strftime('%H:%M:%S')}）",
        title="云邻e家 · 临时密码",
        notification_id=NOTIFICATION_TEMP_PASSCODE,
    )
    async_dispatcher_send(hass, SIGNAL_TEMP_PASSCODE)
    hass.bus.async_fire(
        EVENT_TEMP_CREATED,
        {
            **coordinator.event_targets(coordinator.temp_passcode_entity_id()),
            "passcode": passcode,
            "username": username,
            "expire_seconds": expire,
            "expires_at": expires_at.isoformat(),
        },
    )
