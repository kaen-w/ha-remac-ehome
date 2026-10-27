# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [1.3.0] - 2026-10-27

### Changed

- **The activity log is no longer fetched on every poll.** ``status/get`` is
  polled every cycle instead (it is the light, reliable endpoint) and its
  ``lastStatusUpdate`` stamp — the epoch-ms time of the newest report the
  gateway forwarded, verified against real unlocks and door events — decides
  whether ``log/list`` is worth a request at all. A safety fetch every 10 polls
  covers a missed stamp, and a failed fetch is retried on the very next cycle so
  an event is never swallowed.

  At a 3 s interval this is ~28.8k cheap status calls and a few dozen log calls
  per day instead of ~36.7k calls of which 28.8k hit the heavy, occasionally
  flaky log service. Latency is unchanged: the status poll that notices the
  change runs in the same cycle. Status entities (door, battery, online) also
  refresh every cycle now instead of every 4th.

## [1.2.1] - 2026-10-27

### Fixed

- **A used or expired temporary passcode kept sitting in the state.** The code
  is single use, but nothing ever cleared it: after somebody opened the door
  with it — and forever after its TTL ran out — `sensor.*_temporary_passcode`
  (and every dashboard built on it) still displayed the dead code. The
  passcode is now retired as soon as the lock logs a temporary-passcode unlock
  or the expiry time passes: the state drops to unknown, `status` becomes
  `used`/`expired`, `used_at`/`expired_at` record when, the persistent
  notification carrying the secret is dismissed, and a
  `remac_ehome_temp_password_retired` bus event fires.
- A spent/expired verdict now survives a Home Assistant restart instead of
  resurrecting the old code from the restored state.

## [1.2.0] - 2026-10-27

### Changed

- **The activity sensor now says what happened.** Its state used to be a bare
  timestamp (`2026-10-27 22:07:06`), so the device activity log and the logbook
  read `最近动态 → 2026-10-27 22:07:06` and told you nothing. The state is now a
  sentence — `指纹开锁 · 屋主 · 22:06:42`, `密码开锁 · 22:07:02`, `门已打开`,
  `门已关闭` — and the structured record is exposed as `last_event` /
  `last_unlock`. The entity is no longer a diagnostic entity, so it shows up on
  the device card.
- `recent` now carries the last 20 records (was 10), each with a decoded `text`
  field, so dashboards and templates can render a readable timeline without
  re-implementing the decoder.

### Fixed

- **The activity state flickered between two timestamps.** `/device/log/list`
  occasionally answers with a slightly different page, so the head of the list
  could move backwards and the state — and the logbook — oscillated. Records are
  now sorted newest-first and the state only ever advances.

## [1.1.2] - 2026-10-27

### Added

- Recognise keypad passcode unlocks (`openRecord` `0x1100`). Together with
  `0x0200` (fingerprint of a registered credential) and `0x2100` (temporary
  passcode) all three unlock kinds are now labelled.

## [1.1.1] - 2026-10-27

### Fixed

- **Entity names were stuck in English.** Each entity declared both
  `_attr_name` and `_attr_translation_key`; the hardcoded `_attr_name` wins and
  silently bypassed the translation files. Removed the hardcoded names so the
  language of the Home Assistant UI is respected.
- **Login backoff exploded to the 10 minute cap within 20 seconds.** The
  cool-down path raised the same error as a failed login attempt, so every 5 s
  poll doubled the wait even though no login was attempted. Waiting is now a
  distinct `RemacLoginDeferred` condition that never escalates the backoff, and
  it no longer logs an ERROR on every poll.
- **A flaky activity endpoint took the whole integration down.** When
  `/sl/home/device/log/list` answered `9999 智能服务未响应` every entity became
  unavailable. Log fetch failures now keep the cached records, log at most a
  few warnings, and leave the status entities working.

## [1.1.0] - 2026-10-24

### Added

- **Token source mode** (`token_source`): borrow the access token the official
  app is currently using instead of logging in. Required for coexistence,
  because the REMAC account allows only ONE active session — every login
  invalidates all previous tokens (verified experimentally).
- Configurable `scan_interval` (3–60 s, default 5 s) controlling unlock latency.

### Changed

- Default poll interval reduced from 15 s to 5 s.

### Fixed

- Login storm: the account is single-session, so HA and the app trade kicks.
  Login attempts are now rate limited (60 s minimum, growing to 10 min while the
  fight lasts, reset once a session survives 10 minutes) instead of retrying on
  every poll.
- Only a rejected phone/password triggers Home Assistant's re-auth dialog; a
  rejected token is treated as retryable so the UI is not spammed.

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
