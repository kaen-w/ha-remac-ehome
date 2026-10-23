# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-10-24

### Added

- **Token source mode** (`token_source`): borrow the access token the official
  app is currently using instead of logging in. Required for coexistence,
  because the REMAC account allows only ONE active session — every login
  invalidates all previous tokens (verified experimentally).
- Configurable `scan_interval` (3–60 s, default 5 s) controlling unlock latency.

### Changed

- Default poll interval reduced from 15 s to 5 s.

### Documented

- Why the official app feels instant: it holds a private Alibaba EMAS push
  connection on `emas-link-service.aliyuncs.com:9001`, which is not reusable by
  third parties. The gateway exposes zero open TCP ports (full scan), and the
  cloud offers no WebSocket/SSE endpoint.

## [1.0.0] - 2026-10-24

First public release.

### Added

- Door lock integration for REMAC (云邻 e家) / Midea DC gateways
  (`midea.doorlock.031` verified).
- Automatic login using the cloud RSA public key
  (`base64(RSA_PKCS1v15(password))`), with re-login when the short lived
  access token expires.
- Real-time unlock / door events (`remac_ehome_door`) driven by a 15 second
  activity-log poll, so automations react within ~15 s.
- Entities: lock, battery, door state, last activity, temporary passcode,
  online, low battery, plus button / number / text helpers.
- `remac_ehome.generate_temp_password` service and UI button
  (1–30 minutes, one minute steps, matching the vendor app).
- Re-authentication and options flows so credentials can be updated
  without deleting the entry.
- Diagnostics with token, phone number and password redacted.
- Chinese and English translations.
- `docs/PROTOCOL.md` documenting the reverse engineered API.

### Fixed

- Battery now reads `batteryRemaining` instead of the constant
  `BatteryRemaining`, which always reported 100.

### Known limitations

- The lock does not support remote locking/unlocking. Credential management
  (temporary passcodes) is the supported path.
- `openRecord` → unlock method mapping is only confirmed for temporary
  passcodes (`0x2100`).
- Smart pad switches (`remac.padSwitch.001`) are discovered but not exposed,
  because their control command has not been captured.
