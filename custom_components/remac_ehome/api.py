"""Async client for the REMAC (云邻 e家) cloud API.

The endpoints, headers and payloads in this module were recovered by
intercepting the official Android/iOS app. See ``docs/PROTOCOL.md``.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    APP_ID,
    APP_SRC,
    APP_VERSION,
    BASE_URL,
    ERR_AUTH,
    USER_AGENT,
)
from .exceptions import RemacApiError, RemacAuthError, RemacConnectionError
from .rsa import encrypt as rsa_encrypt

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25)
LOGIN_COOLDOWN = 20.0


class RemacApi:
    """Thin wrapper around the REMAC resident cloud API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        device_id: str,
        token: str | None = None,
        mobile: str | None = None,
        password: str | None = None,
        token_source: str | None = None,
    ) -> None:
        self._session = session
        self._device_id = device_id
        self._token = token
        self._mobile = mobile
        self._password = password
        self._token_source = token_source
        self._public_key: str | None = None
        self._user_id: int | None = None
        self._last_login: float = 0.0
        self._login_lock = asyncio.Lock()

    # ------------------------------------------------------------------ props
    @property
    def token(self) -> str | None:
        """Current access token, if any."""
        return self._token

    @property
    def user_id(self) -> int | None:
        """Cloud user id, available after a successful login."""
        return self._user_id

    @property
    def can_login(self) -> bool:
        """Whether stored credentials allow an automatic login."""
        return bool(self._mobile and self._password)

    @property
    def uses_token_source(self) -> bool:
        """True when the token is borrowed from an external source.

        This mode never calls the login endpoint, so it can never invalidate
        the session the official app is using.
        """
        return bool(self._token_source)

    async def _async_pull_token(self) -> bool:
        """Fetch a fresh token from the configured source. Returns True on success."""
        if not self._token_source:
            return False
        try:
            async with self._session.get(
                self._token_source, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return False
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.debug("token source unavailable: %s", err)
            return False
        token = (payload or {}).get("token")
        if not token:
            return False
        if token != self._token:
            _LOGGER.debug("borrowed a fresh access token from %s", self._token_source)
            self._token = token
        return True

    # ---------------------------------------------------------------- headers
    def _headers(self, *, authenticated: bool = True) -> dict[str, str]:
        agent = {
            "deviceId": self._device_id,
            "buildVersion": "260617.2",
            "os": "18.7.8",
            "clientType": "iOS",
            "model": "iPhone13,2",
            "version": APP_VERSION,
            "ip": "127.0.0.1",
        }
        headers = {
            "Content-Type": "application/json",
            "language": "zh_CN",
            "version": "",
            "X-PACKAGES-ENV": "xxxx",
            "User-Agent": USER_AGENT,
            "app-agent": _compact_json(agent),
        }
        if authenticated and self._token:
            headers["Authorization"] = self._token
        return headers

    # ------------------------------------------------------------------- call
    async def _request(
        self, path: str, payload: dict[str, Any], *, authenticated: bool = True
    ) -> dict[str, Any]:
        stamp = time.strftime("%Y%m%d%H%M%S")
        url = f"{BASE_URL}{path}?appId={APP_ID}&src={APP_SRC}&stamp={stamp}"
        body = dict(payload)
        body.setdefault("msgId", uuid.uuid4().hex[:18])
        try:
            async with self._session.post(
                url,
                data=_compact_json(body),
                headers=self._headers(authenticated=authenticated),
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                text = await resp.text()
        except asyncio.TimeoutError as err:
            raise RemacConnectionError(f"timeout calling {path}") from err
        except aiohttp.ClientError as err:
            raise RemacConnectionError(f"cannot reach the REMAC cloud: {err}") from err

        try:
            return json_loads(text)
        except ValueError as err:
            raise RemacApiError(f"non-JSON reply from {path}: {text[:120]}") from err

    async def _request_authed(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Request with automatic re-login on auth failure."""
        data = await self._request(path, payload)
        if data.get("errorCode") == ERR_AUTH:
            if self.uses_token_source:
                _LOGGER.debug("access token rejected, pulling a new one from the source")
                if await self._async_pull_token():
                    data = await self._request(path, payload)
                if data.get("errorCode") == ERR_AUTH:
                    raise RemacAuthError(
                        "the borrowed token was rejected and the source had no newer one "
                        "(open the 云邻 e家 app once so it refreshes its session)"
                    )
            else:
                _LOGGER.debug("access token rejected, attempting re-login")
                await self.async_login()
                data = await self._request(path, payload)
                if data.get("errorCode") == ERR_AUTH:
                    raise RemacAuthError("access token rejected after re-login")
        return data

    # ------------------------------------------------------------------ login
    async def async_login(self) -> str:
        """Log in with the stored credentials and return a fresh token."""
        if self.uses_token_source:
            raise RemacAuthError(
                "this entry borrows its token from a source and must never log in"
            )
        if not self.can_login:
            raise RemacAuthError(
                "no credentials stored; add the account phone number and password"
            )
        async with self._login_lock:
            if self._last_login and (time.monotonic() - self._last_login) < LOGIN_COOLDOWN:
                if self._token:
                    return self._token

            public_key = await self._async_public_key()
            payload = {
                "loginId": self._mobile,
                "password": rsa_encrypt(self._password, public_key),
                "clientId": self._device_id,
                "pushData": {
                    "appDeviceId": "",
                    "appDeviceToken": "",
                    "appDeviceOs": "iOS",
                    "providerNo": "AliyunPush",
                },
                "encrypt": True,
            }
            data = await self._request(
                "/sl/cas/authorize/token", payload, authenticated=False
            )
            code = data.get("errorCode")
            if code != 0:
                raise RemacAuthError(
                    f"login rejected: {code} {data.get('msg')}"
                )
            info = data.get("data") or {}
            token = info.get("accessToken")
            if not token:
                raise RemacAuthError("login succeeded but returned no accessToken")
            self._token = token
            self._user_id = info.get("userId")
            self._last_login = time.monotonic()
            _LOGGER.info(
                "logged in as %s (token ttl advertised %ss)",
                info.get("nickname") or self._mobile,
                info.get("expires"),
            )
            return token

    async def _async_public_key(self) -> str:
        if self._public_key:
            return self._public_key
        data = await self._request(
            "/sl/home/config/getConfig", {"type": "rsa"}, authenticated=False
        )
        keys = ((data.get("data") or {}).get("rsa") or {}).get("publicKey") or []
        if not keys:
            raise RemacApiError("cloud did not return an RSA public key")
        self._public_key = keys[0]
        return self._public_key

    # -------------------------------------------------------------- endpoints
    async def async_validate(self, house_id: str) -> list[dict[str, Any]]:
        """Validate credentials by fetching the device list."""
        if not self._token and self.uses_token_source:
            await self._async_pull_token()
        if not self._token:
            await self.async_login()
        return await self.async_get_devices(house_id)

    async def async_get_devices(self, house_id: str) -> list[dict[str, Any]]:
        """Return every device under ``house_id``.

        ``fields`` is mandatory — omitting it makes the cloud answer
        ``9999 智能服务未响应`` instead of an error.
        """
        data = await self._request_authed(
            "/sl/home/device/v2/list",
            {
                "houseId": house_id,
                "fields": [
                    "domain",
                    "house",
                    "master",
                    "status",
                    "switches",
                    "orviboUid",
                    "remote",
                    "isVirtual",
                    "extraAttr",
                    "td",
                ],
            },
        )
        if data.get("errorCode") != 0:
            raise RemacApiError(
                f"device list failed: {data.get('errorCode')} {data.get('msg')}"
            )
        return data.get("data") or []

    async def async_get_status(self, dev_code: str) -> dict[str, Any]:
        """Return the live status block of one device."""
        data = await self._request_authed(
            "/sl/home/device/status/get",
            {"devCode": dev_code, "requestOrigin": "plugin"},
        )
        if data.get("errorCode") != 0:
            raise RemacApiError(
                f"status get failed: {data.get('errorCode')} {data.get('msg')}"
            )
        return data.get("data") or {}

    async def async_get_logs(
        self, dev_code: str, page_size: int = 20
    ) -> list[dict[str, Any]]:
        """Return the latest activity records (newest first)."""
        data = await self._request_authed(
            "/sl/home/device/log/list",
            {
                "devCode": dev_code,
                "requestOrigin": "plugin",
                "page": {"pageSize": page_size, "pageNo": 1},
            },
        )
        if data.get("errorCode") != 0:
            raise RemacApiError(
                f"log list failed: {data.get('errorCode')} {data.get('msg')}"
            )
        rows = data.get("data")
        return rows if isinstance(rows, list) else []

    async def async_get_lock_users(self, dev_code: str) -> list[dict[str, Any]]:
        """Return every credential stored on the lock.

        The cloud filters by ``userType`` and an untyped request only exposes a
        single bucket, so all known types are swept and merged.
        """
        seen: dict[tuple[Any, Any], dict[str, Any]] = {}
        for user_type in (None, 1, 2, 3, 4):
            body: dict[str, Any] = {"devCode": dev_code, "requestOrigin": "plugin"}
            if user_type is not None:
                body["userType"] = user_type
            try:
                data = await self._request_authed(
                    "/sl/home/device/subdevice/lock/user/list", body
                )
            except RemacAuthError:
                raise
            except (RemacApiError, RemacConnectionError) as err:
                _LOGGER.debug("lock user sweep (userType=%s) failed: %s", user_type, err)
                continue
            rows = data.get("data")
            if not isinstance(rows, list):
                continue
            for row in rows:
                seen.setdefault((row.get("userNo"), row.get("userType")), row)
        return list(seen.values())

    async def async_generate_temp_password(
        self,
        dev_code: str,
        master_code: str,
        username: str,
        expire_seconds: int = 1800,
    ) -> dict[str, Any]:
        """Create a one-time door passcode (60–1800 s)."""
        data = await self._request_authed(
            "/sl/home/device/subdevice/unlock/generate",
            {
                "devCode": dev_code,
                "masterCode": master_code,
                "username": username,
                "expire": expire_seconds,
                "requestOrigin": "plugin",
            },
        )
        if data.get("errorCode") != 0:
            raise RemacApiError(
                f"temp password failed: {data.get('errorCode')} {data.get('msg')}"
            )
        return data.get("data") or {}


# --------------------------------------------------------------------- utils
def _compact_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def json_loads(text: str) -> dict[str, Any]:
    import json

    return json.loads(text)
