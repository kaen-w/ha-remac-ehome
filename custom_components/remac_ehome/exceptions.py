"""Exceptions for the REMAC integration."""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class RemacError(HomeAssistantError):
    """Base error."""


class RemacAuthError(RemacError):
    """Authentication failed or the access token was rejected."""


class RemacLoginDeferred(RemacAuthError):
    """A login is already scheduled and we are still inside the cool-down.

    This is NOT a failure: it must not escalate the backoff, otherwise a fast
    poll loop would inflate the wait to the cap within seconds.
    """


class RemacCredentialsError(RemacAuthError):
    """The stored phone number / password were rejected.

    Only this error should trigger Home Assistant's re-authentication flow.
    A rejected *token* is expected and recoverable: the account is
    single-session, so every login by the official app invalidates ours.
    """


class RemacApiError(RemacError):
    """The cloud returned an unexpected error."""


class RemacConnectionError(RemacError):
    """The cloud could not be reached."""
