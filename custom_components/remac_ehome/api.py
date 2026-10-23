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
from .exceptions import (
    RemacApiError,
    RemacAuthError,
    RemacConnectionError,
    RemacCredentialsError,
)
from .rsa import encrypt as rsa_encrypt

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25)
#: The REMAC account is single-session: whoever logs in last wins. The official
#: app silently re-logs in, so we must not fight it every few seconds. Back off
#: exponentially between login attempts to keep the churn gentle.
#: Minimum seconds between two login attempts, even successful ones. While the
#: app is open the two clients trade kicks; this cap keeps it to ~1 login/minute
#: instead of a request storm. When the app is closed HA simply owns the session.
LOGIN_BACKOFF_START = 60.0
LOGIN_BACKOFF_MAX = 600.0


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
        self._next_login_at: float = 0.0
        self._login_backoff: float = LOGIN_BACKOFF_START
        self._token_born: float = 0.0

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
            # If the token survived a long time before dying, the fight is over
            # (the app is closed again) so forget the accumulated backoff.
            if self._token_born and (time.monotonic() - self._token_born) > LOGIN_BACKOFF_MAX:
                if self._login_backoff != LOGIN_BACKOFF_START:
                    _LOGGER.debug(
                        "session stayed alive for a long time, resetting login backoff"
                    )
                self._login_backoff = LOGIN_BACKOFF_START
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
                try:
                    await self.async_login()
                except RemacCredentialsError:
                    raise
                except RemacAuthError as err:
                    # Back off so we stop kicking the app every few seconds.
                    self._login_backoff = min(
                        LOGIN_BACKOFF_MAX, self._login_backoff * 2
                    )
                    self._next_login_at = time.monotonic() + self._login_backoff
                    _LOGGER.warning(
                        "cannot re-login yet (%s); next attempt in %ds",
                        err,
                        int(self._login_backoff),
                    )
                    raise
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
            now = time.monotonic()
            if now < self._next_login_at:
                raise RemacAuthError(
                    "login deferred to avoid fighting the app over the single "
                    f"session (retrying in {int(self._next_login_at - now)}s)"
                )
            # Being kicked soon after logging in means the app is open and we
            # lost the race; slow down instead of escalating.
            if self._last_login and (now - self._last_login) < self._login_backoff * 2:
                self._login_backoff = min(
                    LOGIN_BACKOFF_MAX, self._login_backoff * 1.5
                )

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
                # 3153 / 4003 mean "bad credentials" -> user must fix them.
                # 3000 and friends are transient; treat as retryable.
                if code in (3153, 4003):
                    raise RemacCredentialsError(
                        f"login rejected: {code} {data.get('msg')}"
                    )
                raise RemacAuthError(f"login rejected: {code} {data.get('msg')}")
            info = data.get("data") or {}
            token = info.get("accessToken")
            if not token:
                raise RemacAuthError("login succeeded but returned no accessToken")
            self._token = token
            self._user_id = info.get("userId")
            self._last_login = time.monotonic()
            self._token_born = self._last_login
            # Even on success, refuse to log in again for a while. Without this
            # the app would kick us every few seconds and we would kick back,
            # hammering the login endpoint.
            self._next_login_at = self._last_login + self._login_backoff
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

        A single untyped call returns all buckets — passing ``userType`` makes no
        difference (verified for values 1-5), so no sweep is needed.
        """
        data = await self._request_authed(
            "/sl/home/device/subdevice/lock/user/list",
            {"devCode": dev_code, "requestOrigin": "plugin"},
        )
        rows = data.get("data")
        return rows if isinstance(rows, list) else []

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
