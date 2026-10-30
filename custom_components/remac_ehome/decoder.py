"""Decode REMAC / Midea door lock activity records.

A record looks like ``{"data": "{\"openRecord\": 8448}", "createTime": ...}``.
``openRecord`` is a bitfield; the table below only lists values that have been
confirmed against a real lock.
"""
from __future__ import annotations

import json
from typing import Any

#: ``openRecord`` encoding, confirmed on a physical ``midea.doorlock.031``.
#:
#: It is **not** a bitfield of credentials — it is ``(category << 8) | member``:
#:
#:   ``0x0200`` (512)  -> category ``0x02`` (指纹), member ``0``  -> user 0
#:   ``0x0201`` (513)  -> category ``0x02`` (指纹), member ``1``  -> user 1
#:   ``0x1100`` (4352) -> category ``0x11`` (普通密码), member ``0``
#:   ``0x2100`` (8448) -> category ``0x21`` (临时密码), member ``0``
#:
#: The older reading ("bit ``9 + N`` = credential ``N``") looked right only
#: because user 0 happens to land on bit 9; it predicted ``0x0400`` for user 1,
#: which never appears, and it reported ``0x0201`` as user 0 as well — so an
#: unlock by the second registered fingerprint was announced as the first user's.
#: See ``docs/PROTOCOL.md`` §10 for the data that settled it.
#: The high byte matches the credential type Midea's own door-lock SDK uses
#: (``DoorLockKeyInfo.KEY_TYPE_*`` in 美的美居, extracted from the APK):
#: 1 = password, 2 = fingerprint, 3 = RFID card, 4 = mechanical key.
#: Fingerprint (``0x02``) is confirmed by real records; ``0x03``/``0x04`` are that
#: same enum applied to this lock, which has simply never reported a card or the
#: mechanical key. The keypad passcodes use their own codes (``0x11`` / ``0x21``).
RECORD_CATEGORIES: dict[int, str] = {
    0x02: "指纹",
    0x03: "感应卡",
    0x04: "钥匙",
    0x11: "密码",
    0x21: "临时密码",
}

#: Exact values whose category is not known yet, but whose meaning is.
RECORD_METHODS: dict[int, str] = {
    0x1100: "密码",
    0x2100: "临时密码",
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
        _decode_open_record(event, value, user_map)

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
        if event.get("credential_confirmed") is False:
            # The record carried bits we cannot explain, so the method is all we
            # know: never put a person's name on it.
            return f"{text} · 待确认"
        name = event.get("user_name") or event.get("user_label")
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

def _decode_open_record(
    event: dict[str, Any], value: int, user_map: dict[str, Any] | None
) -> None:
    """Fill in the unlock method, and the person only when the record says so.

    ``openRecord`` is ``(category << 8) | member``. Category ``0x02`` means "a
    member's fingerprint" and ``member`` is the credential number, so ``0x0201``
    is user 1 — not user 0 with a mysterious extra bit.

    The old rule ("bit ``9 + N``") ignored the low byte, which is why an evening
    unlock by the *second* fingerprint was announced as the first user. When the
    member is missing from the credential ledger, or the category is unknown, the
    method is still reported but nobody is named.
    """
    category, member = value >> 8, value & 0xFF
    method = RECORD_CATEGORIES.get(category)
    if method is None:
        method = RECORD_METHODS.get(value)

    if method is not None:
        event["category"] = f"0x{category:02X}"
        event["member"] = member
    if method == "临时密码":
        event["temporary"] = True

    if method in ("指纹", "感应卡"):
        info = _credential(str(member), user_map)
        if info is not None:
            name, type_name = info
            # The ledger entry must also *be* that kind of credential: keyId 0 of
            # a card record is not the fingerprint stored as user 0.
            if normalise_method(type_name) != method:
                info = None
        if info is None:
            # A credential we cannot map (empty ledger, or a member the app does
            # not list). Keep the method, refuse to invent a name.
            event["credential_confirmed"] = False
        else:
            name, type_name = info
            event["credential_confirmed"] = True
            event["user_no"] = str(member)
            if name:
                event["user_name"] = name
            else:
                # The app shows this credential by position when it has no name,
                # so "凭证2" is still enough to tell it apart from the first one.
                event["user_label"] = f"凭证{int(member) + 1}"
            if type_name:
                event["user_type"] = type_name
                method = normalise_method(type_name, default=method)
    elif method is None:
        event["unmatched_bits"] = [bit for bit in range(24) if (value >> bit) & 1]

    event["method"] = method or "未知"
    event["record_label"] = f"{event['method']}({event['record_hex']})"


def _credential(
    user_no: str, user_map: dict[str, Any] | None
) -> tuple[str | None, str | None] | None:
    """Return ``(name, type_name)`` for a credential number, if it is known."""
    if not user_map or user_no not in user_map:
        return None
    info = user_map[user_no]
    if isinstance(info, dict):
        return info.get("name"), info.get("type")
    return str(info), None
