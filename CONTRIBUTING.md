# Contributing

Thanks for helping out! The most valuable contributions right now are
**captured protocol samples**, not code.

## Most wanted: door lock samples

The `openRecord` bitfield is only partially decoded (see
[docs/PROTOCOL.md §5](docs/PROTOCOL.md)). To help:

1. Open the door once with a **fingerprint**
2. Open it once with a **passcode**
3. Open it once with an **RFID card** (if you have one)
4. Paste the `recent` attribute of `sensor.<lock>_last_activity` into an issue

Please redact anything you consider private. `createTime` values alone are
harmless.

## Code contributions

```bash
# lint
pip install ruff
ruff check custom_components
ruff format --check custom_components
```

Guidelines:

- Keep the integration dependency free — HA ships no `cryptography` guarantee,
  which is why `rsa.py` is a hand written PKCS#1 v1.5 implementation.
- Never log tokens, phone numbers or passwords. Use `async_redact_data` in
  diagnostics.
- Translations must stay in sync: `strings.json` and every file under
  `translations/` need the same keys.

## Reporting bugs

Include:

- The integration version
- Home Assistant version
- Debug log (`custom_components.remac_ehome: debug`)
- Diagnostics file (Settings → Devices & Services → integration → ⋮ →
  Download diagnostics) — it is already redacted
