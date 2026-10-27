"""Decode REMAC / Midea door lock activity records.

A record looks like ``{"data": "{\"openRecord\": 8448}", "createTime": ...}``.
``openRecord`` is a bitfield; the table below only lists values that have been
confirmed against a real lock.
"""
from __future__ import annotations

import json
from typing import Any

#: ``openRecord`` encoding, confirmed on a physical ``midea.doorlock.031``:
#:
#:   bit ``9 + N``  -> credential number ``N``
#:
#: ``user 0 -> bit 9 -> 0x0200 (512)``, which matches the device's own
#: ``RegisterLockUser: [512]`` list, so the rule is solid.
#:
#: Confirmed samples on a physical lock (fingerprint + passcode + temp passcode):
#:
#:   0x0200 (512)  -> fingerprint of registered user 0   (bit 9)
#:   0x1100 (4352) -> keypad passcode
#:   0x2100 (8448) -> temporary passcode
#:
#: The passcode kinds set bit 8 and then a slot bit above the credential range
#: (bit 12 = passcode, bit 13 = temporary passcode). Those slots have no entry
#: in the credential list, so they are matched by exact value.
RECORD_METHODS: dict[int, str] = {
    0x1100: "密码",
    0x2100: "临时密码",
}
#: Lowest bit used for credential numbers.
USER_BIT_BASE = 9

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


#: Map a credential's ``typeName`` to a short, automatable method name.
TYPE_ALIASES: tuple[tuple[str, str], ...] = (
    ("指纹", "指纹"),
    ("密码", "密码"),
    ("感应卡", "感应卡"),
    ("卡片", "感应卡"),
    ("人脸", "人脸"),
    ("钥匙", "钥匙"),
)


def normalise_method(type_name: str | None, default: str = "未知") -> str:
    """Turn a verbose ``typeName`` such as "普通指纹" into "指纹"."""
    if not type_name:
        return default
    for needle, label in TYPE_ALIASES:
        if needle in type_name:
            return label
    return type_name


def decode_record(
    raw: Any, user_map: dict[str, Any] | None = None
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
        # Derive the method from the credential that owns the matching bit —
        # this scales to any number of users. Only when no *registered* user
        # matches do we fall back to the exact-value table, and otherwise stay
        # honest with "未知" instead of guessing.
        method = _attach_user(event, value, user_map)
        if method is None:
            method = RECORD_METHODS.get(value)
            if method == "临时密码":
                event["temporary"] = True
        event["method"] = method or "未知"
        event["record_label"] = f"{method}({event['record_hex']})"

    if field == "doorState":
        event["door_open"] = value == DOOR_OPEN
        event["door_label"] = "门已打开" if value == DOOR_OPEN else "门已关闭"

    if field == "outsideOpen":
        event["door_label"] = "室外开锁"

    return event


def describe_event(event: dict[str, Any]) -> str:
    """Turn a decoded record into one short sentence a human can read.

    Raw records are useless in the UI on their own — a bare ``0x0200`` or a
    timestamp tells nobody *what* happened. Everything that ends up in a state,
    an attribute or a logbook line goes through here, so the wording stays
    identical everywhere.
    """
    kind = event.get("type")
    if kind == "unlock":
        method = event.get("method") or "开锁"
        text = f"{method}开锁"
        name = event.get("user_name")
        # "屋主" is information, "普通指纹" would just repeat the method.
        if name and str(name) not in (str(method), str(event.get("user_type") or "")):
            text = f"{text} · {name}"
        return text
    if kind == "outside_open":
        return "室外开锁"
    if kind == "door":
        return "门已打开" if event.get("door_open") else "门已关闭"
    if kind == "battery":
        value = event.get("value")
        return f"电量 {value}%" if value is not None else "电量上报"
    return str(event.get("label") or event.get("field") or "动态")


def latest_temp_unlock(
    events: list[dict[str, Any]], since: str = ""
) -> str | None:
    """Return when a temporary passcode was spent, or ``None`` if it was not.

    The M3 passcode is **single use**: the lock logs one ``0x2100`` unlock when
    somebody opens the door with it, and the code is dead afterwards. This looks
    for the newest such record and only accepts it when it happened at or after
    ``since`` (the moment *our* passcode was created), so a leftover temporary
    unlock from an earlier passcode cannot retire the current one.

    ``events`` must be newest-first and ``since`` uses the same
    ``YYYY-MM-DD HH:MM:SS`` format as the cloud's ``createTime``.
    """
    for event in events:
        if event.get("type") != "unlock":
            continue
        if not (event.get("temporary") or event.get("method") == "临时密码"):
            continue
        stamp = str(event.get("time") or "")
        # The newest temporary unlock is older than our passcode -> still unused.
        return stamp if stamp and stamp >= since else None
    return None


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
    event: dict[str, Any], value: int, user_map: dict[str, Any] | None
) -> str | None:
    """Match the credential bit and return the unlock method for it.

    ``user_map`` maps ``userNo`` to ``{"name": ..., "type": ...}``.
    """
    if not user_map:
        return None
    for user_no, info in user_map.items():
        try:
            bit = USER_BIT_BASE + int(user_no)
        except (TypeError, ValueError):
            continue
        if not value & (1 << bit):
            continue
        if isinstance(info, dict):
            name = info.get("name")
            type_name = info.get("type")
        else:  # tolerate a plain string map
            name, type_name = info, None
        event["user_no"] = user_no
        if name:
            event["user_name"] = name
        if type_name:
            event["user_type"] = type_name
        return normalise_method(type_name)
    return None
