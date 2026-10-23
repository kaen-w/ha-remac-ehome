"""Config, reauth and options flows for REMAC (云邻 e家)."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import RemacApi
from .const import (
    CONF_DEVICE_ID,
    CONF_HOUSE_ID,
    CONF_MOBILE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_SOURCE,
    DEFAULT_DEVICE_ID,
    DEFAULT_HOUSE_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .exceptions import RemacAuthError, RemacError

_LOGGER = logging.getLogger(__name__)

def _interval_selector() -> vol.All:
    return vol.All(
        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
    )


SETUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MOBILE): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_HOUSE_ID, default=DEFAULT_HOUSE_ID): str,
        vol.Optional(CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): _interval_selector(),
        vol.Optional(CONF_TOKEN_SOURCE): str,
    }
)

TOKEN_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TOKEN): str,
        vol.Optional(CONF_MOBILE): str,
        vol.Optional(CONF_PASSWORD): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_MOBILE): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_TOKEN): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): _interval_selector(),
    }
)


async def validate_input(
    hass: HomeAssistant,
    *,
    token: str | None,
    mobile: str | None,
    password: str | None,
    house_id: str,
    device_id: str,
    token_source: str | None = None,
) -> list[dict[str, Any]]:
    """Log in (when needed) and return the device list."""
    session = async_create_clientsession(hass)
    api = RemacApi(
        session,
        device_id=device_id,
        token=token,
        mobile=mobile,
        password=password,
        token_source=token_source,
    )
    return await api.async_validate(house_id)


class RemacConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup and re-authentication."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return RemacOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mobile = user_input[CONF_MOBILE].strip()
            password = user_input.get(CONF_PASSWORD) or ""
            house_id = user_input.get(CONF_HOUSE_ID, DEFAULT_HOUSE_ID).strip()
            device_id = user_input.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID).strip()
            token_source = (user_input.get(CONF_TOKEN_SOURCE) or "").strip() or None

            if not token_source and not password:
                return self.async_show_form(
                    step_id="user",
                    data_schema=SETUP_SCHEMA,
                    errors={"base": "need_credentials"},
                )

            await self.async_set_unique_id(f"remac_{mobile}")
            self._abort_if_unique_id_configured()

            try:
                devices = await validate_input(
                    self.hass,
                    token=None,
                    mobile=mobile,
                    password=password,
                    house_id=house_id,
                    device_id=device_id,
                    token_source=token_source,
                )
            except RemacAuthError:
                errors["base"] = "invalid_auth"
            except RemacError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("unexpected error during setup")
                errors["base"] = "unknown"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    return self.async_create_entry(
                        title=f"云邻e家 ({mobile})",
                        data={
                            CONF_MOBILE: mobile,
                            CONF_PASSWORD: password,
                            CONF_HOUSE_ID: house_id,
                            CONF_DEVICE_ID: device_id,
                            CONF_TOKEN_SOURCE: token_source,
                        },
                        options={
                            CONF_SCAN_INTERVAL: user_input.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                            )
                        },
                    )

        return self.async_show_form(
            step_id="user", data_schema=SETUP_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start a re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user refresh the credentials."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        if user_input is not None:
            mobile = (user_input.get(CONF_MOBILE) or entry.data[CONF_MOBILE]).strip()
            password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
            try:
                await validate_input(
                    self.hass,
                    token=(user_input.get(CONF_TOKEN) or "").strip() or None,
                    mobile=mobile,
                    password=password,
                    house_id=entry.data.get(CONF_HOUSE_ID, DEFAULT_HOUSE_ID),
                    device_id=entry.data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
                )
            except RemacAuthError:
                errors["base"] = "invalid_auth"
            except RemacError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_MOBILE: mobile,
                        CONF_PASSWORD: password,
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=TOKEN_SCHEMA,
            errors=errors,
            description_placeholders={"mobile": str(entry.data.get(CONF_MOBILE, ""))},
        )


class RemacOptionsFlow(OptionsFlow):
    """Update the stored credentials without deleting the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}
        entry = self.config_entry

        if user_input is not None:
            mobile = (user_input.get(CONF_MOBILE) or entry.data[CONF_MOBILE]).strip()
            password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
            try:
                await validate_input(
                    self.hass,
                    token=(user_input.get(CONF_TOKEN) or "").strip() or None,
                    mobile=mobile,
                    password=password,
                    house_id=entry.data.get(CONF_HOUSE_ID, DEFAULT_HOUSE_ID),
                    device_id=entry.data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID),
                )
            except RemacAuthError:
                errors["base"] = "invalid_auth"
            except RemacError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_MOBILE: mobile,
                        CONF_PASSWORD: password,
                    },
                    options={
                        **entry.options,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL,
                            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        ),
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init", data_schema=OPTIONS_SCHEMA, errors=errors
        )
