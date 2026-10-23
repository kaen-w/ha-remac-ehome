"""Constants for the REMAC (云邻 e家) integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "remac_ehome"

BASE_URL: Final = "https://app.smartmideazy.com"
APP_ID: Final = "1010"
APP_SRC: Final = "23"
APP_VERSION: Final = "3.4.0"
USER_AGENT: Final = (
    f"SmartLifeCommunity/{APP_VERSION} (iPhone; iOS 18.7.8; Scale/3.00)"
)

#: Activity-log poll cadence in seconds. This drives unlock/door events.
LOG_INTERVAL: Final = 15
#: Status endpoint is refreshed every Nth log poll.
STATUS_EVERY: Final = 4
#: Lock credential list is refreshed every Nth log poll (~10 minutes).
USERS_EVERY: Final = 40

CONF_TOKEN: Final = "token"
CONF_MOBILE: Final = "mobile"
CONF_PASSWORD: Final = "password"
CONF_HOUSE_ID: Final = "house_id"
CONF_DEVICE_ID: Final = "agent_device_id"

DEFAULT_DEVICE_ID: Final = "0123456789abcdef0123456789abcdef"
DEFAULT_HOUSE_ID: Final = "10000001"

#: Fired for every new door-lock log record.
EVENT_DOOR: Final = f"{DOMAIN}_door"
#: Internal dispatcher signal for the temporary-passcode sensor.
SIGNAL_TEMP_PASSCODE: Final = f"{DOMAIN}_temp_passcode"

SERVICE_TEMP_PASSWORD: Final = "generate_temp_password"

MANUFACTURER: Final = "Midea / REMAC"

#: Cloud error codes.
ERR_OK: Final = 0
ERR_AUTH: Final = 3000
ERR_BAD_CREDENTIALS: Final = 3153
ERR_REFRESH_GONE: Final = 7001
