# Migration

## General rule

Use canonical modules when changing code. Historical imports remain supported to avoid breaking existing scripts, but new development should not target them.

## Module mapping

| Legacy | Canonical |
| --- | --- |
| `hdmi_transfer.config` | `hdmi_transfer.core.config` |
| `hdmi_transfer.prng` | `hdmi_transfer.core.prng` |
| `hdmi_transfer.protocols.*` | `hdmi_transfer.core.protocols.*` |
| `hdmi_transfer.capture.*` | `hdmi_transfer.core.capture.*` |
| `hdmi_transfer.file_handling.*` | `hdmi_transfer.core.file_handling.*` |
| `hdmi_transfer.display.*` | `hdmi_transfer.sender.display.*` |
| `hdmi_transfer.sender.cli.*` | `hdmi_transfer.interfaces.cli.*` |
| `hdmi_transfer.receiver.cli.*` | `hdmi_transfer.interfaces.cli.*` |
| `hdmi_transfer.web.server` | `hdmi_transfer.interfaces.web.app_factory` |

## Entry points

| Use | Entry point |
| --- | --- |
| Sender CLI | `hdmi_transfer.interfaces.cli.send` |
| Receiver CLI | `hdmi_transfer.interfaces.cli.receive` |
| Calibration CLI | `hdmi_transfer.interfaces.cli.calibrate` |
| Sender console | `hdmi_transfer.interfaces.cli.sender_console` |
| Receiver console | `hdmi_transfer.interfaces.cli.receiver_console` |
| Web application | `hdmi_transfer.interfaces.web.create_app` |

## Browser sender

Edit the sources in `src/interfaces/browser_sender/`, not the generated `sender.html`. Rebuild and verify with:

```bash
uv run python tools/build_sender_html.py
uv run python tools/build_sender_html.py --check
```

## Migrating a legacy area

1. Identify the target canonical module.
2. Move the implementation into `domain`, `application`, `adapters` or `interfaces`.
3. Keep the legacy module as an explicit wrapper using `hdmi_transfer.compat.imports.reexport`.
4. Add or update compatibility tests.

## Compatibility policy

- Keep legacy shims while public scripts and historical imports need them.
- Target canonical modules in new tests.
- Set `HDMI_EXFIL_WARN_LEGACY_IMPORTS=1` to identify imports that need migration.

## Patterns to avoid

- A second protocol implementation in the browser sender.
- Decoding logic in `receiver_worker.py` or a Flask route.
- Session logic in `sender/cli/send.py` or `receiver/cli/receive.py`.
- Ad hoc capture lifecycle management in web code.
