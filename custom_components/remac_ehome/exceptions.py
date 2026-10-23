"""Exceptions for the REMAC integration."""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class RemacError(HomeAssistantError):
    """Base error."""


class RemacAuthError(RemacError):
    """Authentication failed or the access token was rejected."""


class RemacApiError(RemacError):
    """The cloud returned an unexpected error."""


class RemacConnectionError(RemacError):
    """The cloud could not be reached."""
