# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [1.4.3] - 2026-10-27

### Changed

- Decode unlocks by RFID card (``0x03xx``) and by the mechanical key (``0x04xx``)
  as well. 美的美居's own door-lock SDK ships the enum
  ``DoorLockKeyInfo.KEY_TYPE_*``: 1 = password, 2 = fingerprint, 3 = RFID card,
  4 = mechanical key — and the fingerprint value 2 is exactly the high byte of
  the ``0x0200`` records this lock reports, which is what confirmed the
  ``(keyType << 8) | keyId`` reading. A card is only named when the ledger entry
  for that ``keyId`` really is a card, otherwise the record stays 待确认.

### Documentation

- ``docs/MEIJU-COMPARE.md``: what the lock can do under 美的美居 but not under
  云邻e家, from a static analysis of 美居 11.7.15.3 — remote unlock, electronic
  deadbolt, six alarm types, BLE + MCU firmware OTA, per-use credential
  validity, Zigbee commissioning, and 4 credential kinds. Includes the caveat
  that a Midea gateway is required for anything remote.

## [1.4.2] - 2026-10-27

### Changed

- Logbook event rows also carry the entity's display name, so the Activity list
  renders "指纹开锁 · 家人" under "智能门锁" instead of an unnamed entry.

## [1.4.1] - 2026-10-27

### Fixed

- **The events still did not appear in the device's Activity tab.** The logbook
  can describe them, but a *filtered* logbook query (entity or device) only
  matches events whose event data carries ``entity_id`` or ``device_id`` — ours
  carried just ``dev_code``. Door events now ship ``entity_id`` (the lock) and
  ``device_id``, passcode events the passcode sensor, so the device page shows
  them alongside the state changes.

## [1.4.0] - 2026-10-27

### Added

- **The events now show up in the logbook and in the device's Activity tab.**
  They were plain bus events, which the Activity tab does not render, so it only
  ever showed "最近动态 已变为 …" state lines — and after a restart it showed
  nothing but the passcode entities coming back, which is how a harmless reload
  could look like somebody had created a temporary passcode. A new
  ``logbook.py`` platform describes ``remac_ehome_door``,
  ``remac_ehome_temp_password_created`` and ``remac_ehome_temp_password_retired``,
  attributing each one to the lock or the passcode sensor, with a readable
  message ("指纹开锁 · 家人", "门已打开", "电量 17%", "生成临时密码（访客，30
  分钟有效）", "临时密码（访客）已被使用，已失效") and an icon.
- Both passcode events now also carry ``dev_code``, so they can be attributed to
  the right device when several locks exist.

## [1.3.4] - 2026-10-27

### Fixed

- **Every use of the official app made all entities blink unavailable.** The
  account is single session, so opening the app invalidates our token; the
  integration then sits in its login back-off for up to a minute and used to
  fail the poll, which took every entity to ``unavailable`` and wrote one
  logbook line per entity on the way back (including the passcode entities,
  which made it look like a temporary passcode had been created). A cool-down
  now keeps serving the cached data for up to :data:`MAX_DEFERRED_POLLS` polls
  (60 s at a 3 s interval) and only reports a failure when it really drags on.

  This was observed live: renaming a credential in the app at 15:33 kicked the
  token, the poll failed at 15:34:01 with "login already scheduled, waiting
  another 36s", and the logbook gained `临时密码`/`临时密码使用者` entries 39
  seconds later when the entities came back.

## [1.3.3] - 2026-10-27

### Fixed

- **A login cool-down crashed the poller with a TypeError.** ``UpdateFailed``
  takes no ``log_message`` argument, so every deferred poll raised
  ``TypeError: HomeAssistantError.__init__() got an unexpected keyword argument
  'log_message'`` and Home Assistant logged it as "Unexpected error fetching …
  data" with a full traceback. Home Assistant already logs the first failure of
  a streak at ERROR and downgrades the rest to debug, so the extra argument was
  both wrong and unnecessary — it is simply gone.

## [1.3.2] - 2026-10-27

### Fixed

- **Unlocks by the second fingerprint were reported as the first user.** The
  record was decoded with "bit ``9 + N`` = credential ``N``", which happens to
  hold only for ``N = 0`` and silently ignored the low byte, so ``0x0201`` was
  announced as user 0. ``openRecord`` is actually
  ``(category << 8) | member``: ``0x0200`` = member 0, ``0x0201`` = member 1,
  ``0x1100`` = keypad passcode, ``0x2100`` = temporary passcode.

  It surfaced as an evening unlock that HA attributed to a household member who
  was not there. Five days of records made the pattern obvious: every ``0x0201``
  fell between 17:35 and 18:57, while ``0x0200`` was scattered across the day.

- A credential the app has not named no longer masquerades as a named one: the
  user ledger keeps ``name = null`` instead of falling back to the type name, so
  the state reads ``指纹开锁 · 凭证2`` instead of ``指纹开锁``. When the member
  cannot be found in the ledger at all the state says ``指纹开锁 · 待确认`` and
  the name is left out — an unconfirmed record never invents a person.

- Unlocks with a category nobody has decoded yet are reported as ``未知`` with
  the raw bits in ``unmatched_bits`` instead of being forced onto a person.

### Documentation

- ``docs/PROTOCOL.md`` §5/§10 rewritten with the correct encoding, the four
  ``0x0201`` evening records that exposed it, and the rule that a record must
  match exactly before a person is named.

## [1.3.1] - 2026-10-27

### Fixed

- **Saving the options could kick the official app offline.** The options flow
  validated the credentials by logging in even when the entry runs in
  token-source mode — which by definition must never log in. It now validates
  through the token source instead.
- The options form had an "access token" field that was validated and then
  thrown away (the token was never stored), and the token-source URL could only
  be set once, when the integration was first added. The form now edits the
  token-source URL (pre-filled, so submitting it cannot silently disable that
  mode), the phone number and the poll interval, and drops the dead token field.

### Documentation

- The README claimed the access token only lives ~15 minutes. It actually lives
  the advertised 7200 s: the log shows `logged in as …` exactly every two hours
  (08:59 -> 10:59 -> 12:59) with no failed retries. The short lifetime was an
  artefact of measuring while the official app was being opened, since every app
  login invalidates all older tokens.

- README brought back in line with 1.3.x: the feature table (20 activity
  records with readable text, single-use passcodes, user ledger), the event
  payload table (``text`` / ``temporary`` / ``user_type`` / ``door_label``), the
  new ``remac_ehome_temp_password_retired`` event, the two-stage polling
  explanation, the configuration field table (poll interval, token source), the
  minimum Home Assistant version, and the troubleshooting entries for slow
  events. The "known limitations" no longer claim that only ``0x2100`` is
  decoded or that token-only operation is unsupported.

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
