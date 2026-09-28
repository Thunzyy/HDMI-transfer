# Architecture

## Goal

The project is organized around a shared transfer engine, a single protocol manifest and thin interfaces. Protocol behavior belongs in shared modules rather than separate UI, CLI or web implementations.

## Layers

```text
src/
  domain/          Canonical protocol data
  application/     Send/receive sessions and events
  adapters/        Capture, storage and technical integrations
  interfaces/      CLI, Flask web interface and browser sender
  compat/          Explicit, tested legacy import shims
```

## Responsibilities

| Layer | Responsibility | Keep out of this layer |
| --- | --- | --- |
| `domain` | Protocol manifest, immutable models, shared constants | I/O, capture, Flask, pygame, OpenCV |
| `application` | Session orchestration, events, progress, send/receive transitions | Direct hardware access, UI rendering |
| `adapters` | Persistent capture, device registry, storage and integrations | Protocol rules |
| `interfaces` | CLI commands, web routes, preview, sender HTML generation | Protocol state machines and decoding heuristics |
| `compat` | Consistent legacy re-exports and warning behavior | New product logic |

## Sources of truth

- `hdmi_transfer.domain.protocol_manifest` defines profiles, magic values, header sizes and parameters exposed to the browser sender.
- `tools/build_sender_html.py` generates `sender.html` and `protocol.generated.js` from the manifest and browser sources. Do not edit the standalone HTML directly.
- `hdmi_transfer.application.send_session.SendSession` and `hdmi_transfer.application.receive_session.ReceiveSession` provide shared state machines. CLI and web interfaces use these services instead of duplicating behavior.

## Sending flow

1. The interface collects user options.
2. `SendSession` reads the payload, builds metadata and produces packets/frame events.
3. The selected renderer displays the frames.
4. The browser sender follows the same wire protocol through generated assets.

## Receiving flow

1. `CaptureManager` opens or reuses a persistent capture handle.
2. The interface reads frames and converts them into sampled grids.
3. `ReceiveSession` detects the protocol, tracks progress and reconstructs the file.
4. Web routes or CLI commands expose events and resulting files.

## Web application

- `hdmi_transfer.interfaces.web.app_factory.create_app` creates the Flask application.
- `routes_devices.py`, `routes_receive.py` and `routes_files.py` define HTTP routes.
- `preview_stream.py` belongs to the interface layer because it serves an HTTP stream; it uses `CaptureManager` for capture.
- `hdmi_transfer.web.server` is a compatibility shim.

## Compatibility

- Historical imports such as `hdmi_transfer.protocols`, `hdmi_transfer.config` and `hdmi_transfer.cli.*` remain available through `hdmi_transfer.compat.imports.reexport`.
- Legacy wrappers can emit warnings when `HDMI_EXFIL_WARN_LEGACY_IMPORTS=1`.
- New contributions should use canonical paths rather than shims.

## Quality checks

- Fountain performance budgets are enforced by `tests/test_fountain_overhead.py` and `tests/perf/test_fountain_budget.py`.
- Check generated browser assets with `uv run python tools/build_sender_html.py --check`.
- Run the local/CI quality gate through `tools/run_quality_gate.ps1`.

## Migration direction

The project is being migrated incrementally. Legacy shims remain while the target architecture is in place. Continue moving behavior into shared modules; do not reintroduce protocol logic into interfaces.
