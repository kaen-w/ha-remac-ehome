"""Decode REMAC / Midea door lock activity records.

A record looks like ``{"data": "{\"openRecord\": 8448}", "createTime": ...}``.
``openRecord`` is a bitfield; the table below only lists values that have been
confirmed against a real lock.
"""
from __future__ import annotations

import json
from typing import Any

#: ``openRecord`` values confirmed on a physical ``midea.doorlock.031``.
#: Extend this table when new samples are captured.
RECORD_METHODS: dict[int, str] = {
    0x2100: "临时密码",
    0x0200: "指纹",
    0x1200: "密码",
}

#: Which payload field a record carries, and how to label it.
FIELD_TYPES: dict[str, tuple[str, str]] = {
    "openRecord": ("unlock", "开锁"),
    "outsideOpen": ("outside_open", "室外开锁"),
    "doorState": ("door", "门磁"),
    "batteryRemaining": ("battery", "电量"),
}

#: ``doorState`` values.
DOOR_OPEN = 0
DOOR_CLOSED = 1


def decode_record(
    raw: Any, user_map: dict[str, str] | None = None
) -> dict[str, Any]:
    """Turn one record payload into a structured event dictionary."""
    payload = _as_mapping(raw)
    if not payload:
        return {"type": "unknown", "raw": raw}

    field, value = next(iter(payload.items()))
    event_type, label = FIELD_TYPES.get(field, ("other", field))
    event: dict[str, Any] = {
        "type": event_type,
        "field": field,
        "label": label,
        "value": value,
    }

    if field == "openRecord" and isinstance(value, int):
        event["record_hex"] = f"0x{value:04X}"
        event["bits"] = [bit for bit in range(24) if (value >> bit) & 1]
        event["method"] = RECORD_METHODS.get(value, "未知")
        event["record_label"] = f"{event['method']}({event['record_hex']})"
        _attach_user(event, value, user_map)

    if field == "doorState":
        event["door_open"] = value == DOOR_OPEN
        event["door_label"] = "门已打开" if value == DOOR_OPEN else "门已关闭"

    if field == "outsideOpen":
        event["door_label"] = "室外开锁"

    return event


def _as_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _attach_user(
    event: dict[str, Any], value: int, user_map: dict[str, str] | None
) -> None:
    """Best-effort mapping from an ``openRecord`` value to a credential."""
    if not user_map:
        return
    for user_no, name in user_map.items():
        try:
            bit = 9 + int(user_no)
        except (TypeError, ValueError):
            continue
        if value & (1 << bit):
            event["user_no"] = user_no
            event["user_name"] = name
            return
