"""Logbook descriptions for REMAC events.

Without this module the integration's bus events (`remac_ehome_door`,
`remac_ehome_temp_password_*`) are invisible: the device page's Activity tab only
renders state changes, so a whole stream of unlocks looked like nothing but
"最近动态 已变为 …" lines — or, worse, like nothing at all when the passcode
entities happened to be the only thing changing.

Home Assistant lets an integration describe its own events for the logbook. Each
event is turned into a short message and attributed to the entity it belongs to
(the door lock or the temporary-passcode sensor), which is exactly what makes it
show up under the device's Activity tab and in the recorder history.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, EVENT_DOOR, EVENT_TEMP_CREATED, EVENT_TEMP_RETIRED


@callback
def async_describe_events(hass: HomeAssistant, async_describe_event: Any) -> None:
    """Tell the logbook how to render this integration's events."""

    @callback
    def describe_door_event(event: Any) -> dict[str, Any]:
        data = event.data
        text = data.get("text") or _fallback_text(data)
        record = data.get("record_hex")
        # Keep the raw record for unlocks that we could not attribute to a
        # person, so the activity list is still diagnosable.
        if data.get("credential_confirmed") is False and record:
            text = f"{text}（{record}）"
        entity_id = data.get("entity_id") or _entity_id(hass, data.get("dev_code"), "lock")
        return {
            "icon": _icon(data),
            "message": text,
            "name": _friendly_name(hass, entity_id),
            "entity_id": entity_id,
        }

    @callback
    def describe_created(event: Any) -> dict[str, Any]:
        data = event.data
        minutes = int(data.get("expire_seconds") or 0) // 60
        holder = data.get("username") or "访客"
        entity_id = data.get("entity_id") or _entity_id(hass, data.get("dev_code"), "temp_passcode")
        return {
            "icon": "mdi:key-plus",
            "message": f"生成临时密码（{holder}，{minutes} 分钟有效）",
            "name": _friendly_name(hass, entity_id),
            "entity_id": entity_id,
        }

    @callback
    def describe_retired(event: Any) -> dict[str, Any]:
        data = event.data
        holder = data.get("username") or ""
        who = f"（{holder}）" if holder else ""
        what = "已被使用" if data.get("status") == "used" else "已过期"
        entity_id = data.get("entity_id") or _entity_id(hass, data.get("dev_code"), "temp_passcode")
        return {
            "icon": "mdi:key-remove",
            "message": f"临时密码{who}{what}，已失效",
            "name": _friendly_name(hass, entity_id),
            "entity_id": entity_id,
        }

    async_describe_event(DOMAIN, EVENT_DOOR, describe_door_event)
    async_describe_event(DOMAIN, EVENT_TEMP_CREATED, describe_created)
    async_describe_event(DOMAIN, EVENT_TEMP_RETIRED, describe_retired)


def _entity_id(hass: HomeAssistant, dev_code: Any, key: str) -> str | None:
    """Resolve one of our entities from the door lock's device code."""
    if not dev_code:
        return None
    domain = "lock" if key == "lock" else "sensor"
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{dev_code}_{key}")


def _friendly_name(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Display name for the entity an event belongs to."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    return state.attributes.get("friendly_name") if state else None


def _icon(data: dict[str, Any]) -> str:
    kind = data.get("type")
    if kind == "unlock":
        return "mdi:lock-open-variant"
    if kind == "outside_open":
        return "mdi:door-open"
    if kind == "door":
        return "mdi:door-open" if data.get("door_open") else "mdi:door-closed"
    if kind == "battery":
        return "mdi:battery"
    return "mdi:door"


def _fallback_text(data: dict[str, Any]) -> str:
    """Rebuild a message when the event predates the ``text`` field."""
    kind = data.get("type")
    if kind == "unlock":
        return f"{data.get('method') or '未知'}开锁"
    if kind == "door":
        return "门已打开" if data.get("door_open") else "门已关闭"
    if kind == "outside_open":
        return "室外开锁"
    if kind == "battery":
        return f"电量 {data.get('value')}%"
    return "门锁动态"
