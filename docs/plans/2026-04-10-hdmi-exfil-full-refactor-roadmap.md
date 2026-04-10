# HDMI Exfil Full Refactor Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild HDMI Exfil around one canonical transfer engine, one canonical protocol manifest, and thin CLI/web/browser interfaces while restoring fountain performance and hardening hardware stability.

**Architecture:** Use a strangler refactor. Build the new layers `domain`, `application`, `adapters`, and `interfaces` beside the current tree, then progressively route the existing entry points onto them. The current `core`, `sender`, `receiver`, and `web` modules stay alive during migration, but only as callers or compatibility shims; all protocol state machines, session orchestration, and device lifecycle must converge into shared services.

**Tech Stack:** Python 3.11+, NumPy, Numba, OpenCV, pygame-ce, Flask, vanilla JavaScript, pytest, Hypothesis

## Why This Refactor Exists

- The current direction is good, but actual behavior is still duplicated between CLI receiver, web receiver worker, and browser sender.
- The browser sender is a second protocol implementation, not just a UI.
- Fountain performance is below its documented target for `K >= 100`, so the project cannot claim stable throughput until performance budgets are enforced by tests.
- `server.py` and `receiver_worker.py` carry too many responsibilities, which makes hardware issues and UI issues harder to isolate.
- There are many compatibility shims already; the next step is to turn them into a deliberate migration layer instead of letting them become another permanent architecture.

## Non-Negotiable Rules

- Do not rewrite everything in one cut. Build the new path beside the old path and cut over only after parity tests pass.
- No protocol logic in CLI, Flask routes, or browser UI code.
- No hardware access logic in web route modules.
- One source of truth for protocol constants, profiles, BPC levels, and header layouts.
- Every cutover must be protected by unit tests, contract tests, and at least one loopback smoke path.
- Performance claims must live in tests, not comments.
- Keep backward-compatible imports and scripts working until the final compatibility cleanup task.

## Target End State

```text
src/hdmi_exfil/
  domain/
    __init__.py
    protocol_manifest.py
    models.py
    protocols/
  application/
    __init__.py
    send_session.py
    receive_session.py
    calibration_service.py
    events.py
  adapters/
    __init__.py
    capture/
      __init__.py
      source.py
      capture_manager.py
      device_registry.py
      threaded_capture.py
    display/
      __init__.py
      pygame_renderer.py
      cv2_renderer.py
    storage/
      __init__.py
      settings_store.py
  interfaces/
    __init__.py
    cli/
      __init__.py
      send.py
      receive.py
      calibrate.py
      sender_console.py
      receiver_console.py
    web/
      __init__.py
      app_factory.py
      routes_devices.py
      routes_receive.py
      routes_files.py
      preview_stream.py
    browser_sender/
      __init__.py
      template.html
      app.js
      protocol.generated.js
  compat/
    __init__.py
    imports.py
tools/
  build_sender_html.py
docs/
  architecture.md
  migration.md
```

## Release Gates

- `pytest` must pass on the non-hardware suite.
- `pytest tests/test_fountain_overhead.py -v` must pass with the documented threshold.
- `python tools/build_sender_html.py --check` must pass.
- `hdmi-bench --profile balanced --mode fountain --no-json` must run cleanly.
- `hdmi-calibrate --profile balanced loopback <device>` must still work manually.
- `hdmi-send` and `hdmi-recv` must keep their existing CLI contract until the final cleanup task.

## Phase Order

1. Create a canonical data model and freeze current behavior with tests.
2. Extract shared send/receive application services.
3. Centralize hardware lifecycle and split interfaces.
4. Rebuild browser sender from generated assets.
5. Move CLI and web onto the new architecture.
6. Fix fountain performance and remove dead duplication.
7. Finish with docs, CI, migration, and compatibility policy.

### Task 1: Create Baseline And Canonical Protocol Manifest

**Files:**
- Create: `src/hdmi_exfil/domain/__init__.py`
- Create: `src/hdmi_exfil/domain/protocol_manifest.py`
- Create: `src/hdmi_exfil/domain/models.py`
- Create: `tests/test_protocol_manifest.py`
- Create: `docs/plans/baselines/2026-04-10-refactor-baseline.md`
- Modify: `src/hdmi_exfil/core/config.py`
- Modify: `src/hdmi_exfil/core/prng.py`
- Modify: `src/hdmi_exfil/core/protocols/encoding.py`

**Step 1: Write the failing test**

```python
from hdmi_exfil.domain.protocol_manifest import get_protocol_manifest


def test_protocol_manifest_exposes_profiles_and_headers():
    manifest = get_protocol_manifest()
    assert manifest.profiles["balanced"].width == 1920
    assert manifest.sequential.header_size == 17
    assert manifest.fountain.header_size == 16
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_protocol_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing manifest API.

**Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class ProtocolManifest:
    profiles: dict[str, object]
    sequential: object
    fountain: object


def get_protocol_manifest() -> ProtocolManifest:
    ...
```

Make `src/hdmi_exfil/core/config.py` read from the manifest instead of owning duplicate truth.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_protocol_manifest.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/domain src/hdmi_exfil/core/config.py src/hdmi_exfil/core/prng.py src/hdmi_exfil/core/protocols/encoding.py tests/test_protocol_manifest.py docs/plans/baselines/2026-04-10-refactor-baseline.md
git commit -m "refactor: add canonical protocol manifest"
```

### Task 2: Freeze Existing Behavior With Contract Tests

**Files:**
- Create: `tests/contracts/__init__.py`
- Create: `tests/contracts/helpers.py`
- Create: `tests/contracts/test_protocol_contract.py`
- Create: `tests/contracts/test_send_contract.py`
- Create: `tests/contracts/test_receive_contract.py`
- Create: `tests/fixtures/contracts/README.md`
- Modify: `tests/test_sender_html_magic.py`
- Modify: `tests/test_loopback.py`
- Modify: `tests/test_properties.py`

**Step 1: Write the failing test**

```python
def test_sequential_start_frame_contract():
    contract = build_sequential_contract_fixture()
    assert contract.header_size == 17
    assert contract.magic_hex == "DA7A"
    assert contract.payload_len > 0
```

Add equivalent contract coverage for fountain headers, metadata offsets, and decode acceptance rules.

**Step 2: Run test to verify it fails**

Run: `pytest tests/contracts -v`
Expected: FAIL because the fixture builders and contract helpers do not exist.

**Step 3: Write minimal implementation**

Create test-only helpers that serialize the current protocol behavior into stable fixtures. Do not refactor production code in this task except where needed to expose pure helper functions.

**Step 4: Run test to verify it passes**

Run: `pytest tests/contracts -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/contracts tests/fixtures/contracts/README.md tests/test_sender_html_magic.py tests/test_loopback.py tests/test_properties.py
git commit -m "test: freeze current protocol behavior with contracts"
```

### Task 3: Extract Shared Send Session

**Files:**
- Create: `src/hdmi_exfil/application/__init__.py`
- Create: `src/hdmi_exfil/application/send_session.py`
- Create: `src/hdmi_exfil/application/events.py`
- Create: `tests/test_send_session.py`
- Modify: `src/hdmi_exfil/sender/cli/send.py`
- Modify: `src/hdmi_exfil/sender/cli/console.py`
- Modify: `src/hdmi_exfil/cli/send.py`
- Modify: `tests/test_sender_console.py`

**Step 1: Write the failing test**

```python
from hdmi_exfil.application.send_session import SendSession


def test_send_session_emits_metadata_and_frame_stream(tmp_path):
    file_path = tmp_path / "payload.bin"
    file_path.write_bytes(b"abc" * 100)

    session = SendSession.from_input(
        input_path=str(file_path),
        mode="sequential",
        profile_name="balanced",
    )

    frames = list(session.iter_frame_packets())
    assert frames
    assert frames[0].kind == "start"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_send_session.py -v`
Expected: FAIL because `SendSession` does not exist.

**Step 3: Write minimal implementation**

```python
class SendSession:
    @classmethod
    def from_input(cls, *, input_path: str, mode: str, profile_name: str):
        ...

    def iter_frame_packets(self):
        yield from ()
```

Move file reading, metadata wrapping, and frame sequencing into `SendSession`. Leave renderer choice in the CLI layer.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_send_session.py tests/test_sender_console.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/application src/hdmi_exfil/sender/cli/send.py src/hdmi_exfil/sender/cli/console.py src/hdmi_exfil/cli/send.py tests/test_send_session.py tests/test_sender_console.py
git commit -m "refactor: extract shared send session"
```

### Task 4: Extract Shared Receive Session

**Files:**
- Create: `src/hdmi_exfil/application/receive_session.py`
- Create: `tests/test_receive_session.py`
- Modify: `src/hdmi_exfil/receiver/cli/receive.py`
- Modify: `src/hdmi_exfil/web/receiver_worker.py`
- Modify: `src/hdmi_exfil/cli/receive.py`
- Modify: `tests/test_receiver_worker_sequential.py`
- Modify: `tests/test_receiver_worker_geometry.py`
- Modify: `tests/test_loopback.py`

**Step 1: Write the failing test**

```python
from hdmi_exfil.application.receive_session import ReceiveSession


def test_receive_session_emits_progress_and_complete_events(sampled_frames):
    session = ReceiveSession(mode="auto", profile_name="balanced")
    events = []
    for sampled in sampled_frames:
        events.extend(session.feed_sampled_grid(sampled))
    assert any(event.kind == "complete" for event in events)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_receive_session.py -v`
Expected: FAIL because `ReceiveSession` does not exist.

**Step 3: Write minimal implementation**

```python
class ReceiveSession:
    def __init__(self, *, mode: str, profile_name: str):
        ...

    def feed_sampled_grid(self, sampled):
        return []
```

Move protocol detection, frame classification, state transitions, completion, and progress events into the session. Leave frame acquisition and UI rendering outside.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_receive_session.py tests/test_receiver_worker_sequential.py tests/test_receiver_worker_geometry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/application/receive_session.py src/hdmi_exfil/receiver/cli/receive.py src/hdmi_exfil/web/receiver_worker.py src/hdmi_exfil/cli/receive.py tests/test_receive_session.py tests/test_receiver_worker_sequential.py tests/test_receiver_worker_geometry.py tests/test_loopback.py
git commit -m "refactor: extract shared receive session"
```

### Task 5: Create Capture Manager And Fix Lifecycle Behavior

**Files:**
- Create: `src/hdmi_exfil/adapters/__init__.py`
- Create: `src/hdmi_exfil/adapters/capture/__init__.py`
- Create: `src/hdmi_exfil/adapters/capture/device_registry.py`
- Create: `src/hdmi_exfil/adapters/capture/capture_manager.py`
- Create: `src/hdmi_exfil/adapters/capture/threaded_capture.py`
- Create: `tests/test_capture_manager.py`
- Modify: `src/hdmi_exfil/receiver/capture/source.py`
- Modify: `src/hdmi_exfil/core/capture/threaded.py`
- Modify: `src/hdmi_exfil/receiver/cli/console.py`
- Modify: `src/hdmi_exfil/web/server.py`
- Modify: `tests/test_threaded_capture.py`

**Step 1: Write the failing test**

```python
def test_capture_manager_reuses_matching_persistent_handle(fake_capture):
    manager = CaptureManager()
    manager.prime(device=1, backend=42, capture=fake_capture)
    cap = manager.take(device=1)
    assert cap is fake_capture
```

Add a second test proving failed reads back off instead of spinning.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_capture_manager.py tests/test_threaded_capture.py -v`
Expected: FAIL because `CaptureManager` and the backoff behavior do not exist.

**Step 3: Write minimal implementation**

```python
class CaptureManager:
    def prime(self, *, device: int, backend: int, capture):
        ...

    def take(self, *, device: int):
        ...
```

Replace ad hoc persistent-capture logic in `server.py` with this adapter. Make `threaded_capture` sleep briefly on failed reads.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_capture_manager.py tests/test_threaded_capture.py tests/test_receiver_console.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/adapters/capture src/hdmi_exfil/receiver/capture/source.py src/hdmi_exfil/core/capture/threaded.py src/hdmi_exfil/receiver/cli/console.py src/hdmi_exfil/web/server.py tests/test_capture_manager.py tests/test_threaded_capture.py
git commit -m "refactor: centralize capture lifecycle management"
```

### Task 6: Split Web App Into Thin Interface Modules

**Files:**
- Create: `src/hdmi_exfil/interfaces/__init__.py`
- Create: `src/hdmi_exfil/interfaces/web/__init__.py`
- Create: `src/hdmi_exfil/interfaces/web/app_factory.py`
- Create: `src/hdmi_exfil/interfaces/web/routes_devices.py`
- Create: `src/hdmi_exfil/interfaces/web/routes_receive.py`
- Create: `src/hdmi_exfil/interfaces/web/routes_files.py`
- Create: `src/hdmi_exfil/interfaces/web/preview_stream.py`
- Create: `tests/test_web_app_factory.py`
- Modify: `src/hdmi_exfil/web/server.py`
- Modify: `src/hdmi_exfil/web/__main__.py`
- Modify: `tests/test_server_receive_file_api.py`

**Step 1: Write the failing test**

```python
def test_create_app_registers_receive_and_file_routes():
    app = create_app()
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/receive/start" in rules
    assert "/api/receive/file/<path:filename>" in rules
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_app_factory.py -v`
Expected: FAIL because the new app factory module does not exist.

**Step 3: Write minimal implementation**

```python
def create_app(output_dir: str = "received_files"):
    app = Flask(__name__)
    register_device_routes(app)
    register_receive_routes(app)
    register_file_routes(app)
    return app
```

Keep `src/hdmi_exfil/web/server.py` as a thin shim that imports `create_app` from the new interface package.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_web_app_factory.py tests/test_server_receive_file_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/interfaces/web src/hdmi_exfil/web/server.py src/hdmi_exfil/web/__main__.py tests/test_web_app_factory.py tests/test_server_receive_file_api.py
git commit -m "refactor: split web app into interface modules"
```

### Task 7: Rebuild Browser Sender From Source Modules And Generated Assets

**Files:**
- Create: `src/hdmi_exfil/interfaces/browser_sender/__init__.py`
- Create: `src/hdmi_exfil/interfaces/browser_sender/template.html`
- Create: `src/hdmi_exfil/interfaces/browser_sender/app.js`
- Create: `src/hdmi_exfil/interfaces/browser_sender/protocol.generated.js`
- Create: `tools/build_sender_html.py`
- Create: `tests/test_sender_build.py`
- Modify: `sender.html`
- Modify: `src/hdmi_exfil/web/static/sender-page.html`
- Modify: `tests/test_sender_html_magic.py`

**Step 1: Write the failing test**

```python
def test_build_sender_html_uses_protocol_manifest(tmp_path):
    output = build_sender_html(tmp_path / "sender.html")
    text = output.read_text(encoding="utf-8")
    assert "const SEQ_MAGIC = 0xDA7A;" in text
    assert "const FOUNTAIN_MAGIC" in text
```

Add a second test proving the generated asset is reproducible byte-for-byte when the manifest does not change.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_sender_build.py -v`
Expected: FAIL because the build script and module source files do not exist.

**Step 3: Write minimal implementation**

```python
def build_sender_html(output_path):
    manifest = get_protocol_manifest()
    ...
    return output_path
```

Move the hand-maintained protocol constants out of `sender.html`. Make `sender.html` a generated artifact, not a source file you edit manually.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_sender_build.py tests/test_sender_html_magic.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/interfaces/browser_sender tools/build_sender_html.py sender.html src/hdmi_exfil/web/static/sender-page.html tests/test_sender_build.py tests/test_sender_html_magic.py
git commit -m "refactor: generate browser sender from shared manifest"
```

### Task 8: Move CLI Entry Points Into The Interface Layer

**Files:**
- Create: `src/hdmi_exfil/interfaces/cli/__init__.py`
- Create: `src/hdmi_exfil/interfaces/cli/send.py`
- Create: `src/hdmi_exfil/interfaces/cli/receive.py`
- Create: `src/hdmi_exfil/interfaces/cli/calibrate.py`
- Create: `src/hdmi_exfil/interfaces/cli/sender_console.py`
- Create: `src/hdmi_exfil/interfaces/cli/receiver_console.py`
- Modify: `pyproject.toml`
- Modify: `src/hdmi_exfil/sender/cli/send.py`
- Modify: `src/hdmi_exfil/receiver/cli/receive.py`
- Modify: `src/hdmi_exfil/receiver/cli/calibrate.py`
- Modify: `src/hdmi_exfil/sender/cli/console.py`
- Modify: `src/hdmi_exfil/receiver/cli/console.py`
- Modify: `tests/test_sender_console.py`
- Modify: `tests/test_receiver_console.py`

**Step 1: Write the failing test**

```python
def test_cli_entry_points_import_from_interfaces_layer():
    from hdmi_exfil.interfaces.cli.send import main as send_main
    from hdmi_exfil.interfaces.cli.receive import main as receive_main
    assert callable(send_main)
    assert callable(receive_main)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_sender_console.py tests/test_receiver_console.py -v`
Expected: FAIL because the new interface modules do not exist.

**Step 3: Write minimal implementation**

```python
def main() -> None:
    ...
```

Make the CLI modules thin wrappers over `SendSession`, `ReceiveSession`, and the new capture manager. Update `pyproject.toml` entry points only after the new modules pass.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_sender_console.py tests/test_receiver_console.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/interfaces/cli pyproject.toml src/hdmi_exfil/sender/cli/send.py src/hdmi_exfil/receiver/cli/receive.py src/hdmi_exfil/receiver/cli/calibrate.py src/hdmi_exfil/sender/cli/console.py src/hdmi_exfil/receiver/cli/console.py tests/test_sender_console.py tests/test_receiver_console.py
git commit -m "refactor: move cli entry points into interfaces layer"
```

### Task 9: Restore Fountain Performance And Add Performance Gates

**Files:**
- Create: `src/hdmi_exfil/core/protocols/fountain_tuning.py`
- Create: `tests/perf/test_fountain_budget.py`
- Modify: `src/hdmi_exfil/core/protocols/degree.py`
- Modify: `src/hdmi_exfil/core/protocols/fountain.py`
- Modify: `src/hdmi_exfil/core/prng.py`
- Modify: `tests/test_fountain_overhead.py`
- Modify: `tests/test_fountain_ge.py`
- Modify: `tests/test_rsd.py`
- Modify: `tests/test_rsd_cross_language.py`

**Step 1: Write the failing test**

```python
def test_fountain_budget_k100():
    avg_overhead = measure_budget(K=100, runs=20)
    assert avg_overhead < 1.10
```

Add the equivalent checks for `K=500` and `K=1000`, and assert that documented tuning metadata matches actual thresholds.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_fountain_overhead.py -v`
Expected: FAIL with the same overhead regression currently observed.

**Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class FountainTuning:
    c: float
    delta: float
    ge_max_total_chunks: int
    ge_max_unknowns: int
```

Move magic tuning constants out of comments and into code. Retune degree sampling and GE guardrails until the budget tests pass. Delete or rewrite any stale performance claims.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_fountain_overhead.py tests/perf/test_fountain_budget.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/core/protocols/fountain_tuning.py src/hdmi_exfil/core/protocols/degree.py src/hdmi_exfil/core/protocols/fountain.py src/hdmi_exfil/core/prng.py tests/perf/test_fountain_budget.py tests/test_fountain_overhead.py tests/test_fountain_ge.py tests/test_rsd.py tests/test_rsd_cross_language.py
git commit -m "perf: restore fountain overhead budget"
```

### Task 10: Collapse Duplicates Into An Explicit Compatibility Layer

**Files:**
- Create: `src/hdmi_exfil/compat/__init__.py`
- Create: `src/hdmi_exfil/compat/imports.py`
- Create: `tests/test_compat_imports.py`
- Modify: `src/hdmi_exfil/config.py`
- Modify: `src/hdmi_exfil/prng.py`
- Modify: `src/hdmi_exfil/capture/sampler.py`
- Modify: `src/hdmi_exfil/capture/source.py`
- Modify: `src/hdmi_exfil/capture/threaded.py`
- Modify: `src/hdmi_exfil/cli/send.py`
- Modify: `src/hdmi_exfil/cli/receive.py`
- Modify: `src/hdmi_exfil/cli/calibrate.py`
- Modify: `src/hdmi_exfil/cli/sender_console.py`
- Modify: `src/hdmi_exfil/cli/receiver_console.py`
- Modify: `src/hdmi_exfil/display/monitors.py`
- Modify: `src/hdmi_exfil/display/renderer.py`
- Modify: `src/hdmi_exfil/display/test_patterns.py`
- Modify: `src/hdmi_exfil/file_handling/metadata.py`
- Modify: `src/hdmi_exfil/file_handling/reader.py`
- Modify: `src/hdmi_exfil/file_handling/writer.py`
- Modify: `src/hdmi_exfil/protocols/__init__.py`
- Modify: `src/hdmi_exfil/protocols/base.py`
- Modify: `src/hdmi_exfil/protocols/degree.py`
- Modify: `src/hdmi_exfil/protocols/fountain.py`
- Modify: `src/hdmi_exfil/protocols/sequential.py`
- Modify: `src/hdmi_exfil/protocols/xor_ops.py`

**Step 1: Write the failing test**

```python
def test_legacy_imports_resolve_to_new_canonical_modules():
    import hdmi_exfil.protocols.fountain as legacy_fountain
    from hdmi_exfil.core.protocols.fountain import FountainProtocol
    assert legacy_fountain.FountainProtocol is FountainProtocol
```

Add equivalent import tests for config, capture, file handling, and CLI wrappers.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_compat_imports.py -v`
Expected: FAIL because the new compatibility helpers do not exist.

**Step 3: Write minimal implementation**

```python
def reexport(module_name: str):
    ...
```

Make all legacy modules explicit wrappers with one pattern and one warning strategy. Do not leave ad hoc behavior in old modules.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_compat_imports.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/hdmi_exfil/compat src/hdmi_exfil/config.py src/hdmi_exfil/prng.py src/hdmi_exfil/capture src/hdmi_exfil/cli src/hdmi_exfil/display src/hdmi_exfil/file_handling src/hdmi_exfil/protocols tests/test_compat_imports.py
git commit -m "refactor: formalize compatibility shims"
```

### Task 11: Final Cutover, Documentation, And Quality Gate

**Files:**
- Create: `docs/architecture.md`
- Create: `docs/migration.md`
- Create: `.github/workflows/ci.yml`
- Create: `tools/run_quality_gate.ps1`
- Modify: `README.md`
- Modify: `docs/testing.md`
- Modify: `docs/hardware-setup.md`
- Modify: `pyproject.toml`

**Step 1: Write the failing test**

```python
def test_quality_gate_script_lists_required_checks():
    text = Path("tools/run_quality_gate.ps1").read_text(encoding="utf-8")
    assert "pytest" in text
    assert "test_fountain_overhead.py" in text
```

Add a second test or smoke assertion that the CI workflow references the same gate commands as the local script.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_sender_build.py tests/test_protocol_manifest.py -v`
Expected: PASS for prior tasks, but the new quality gate docs and scripts do not exist yet.

**Step 3: Write minimal implementation**

```powershell
pytest
pytest tests/test_fountain_overhead.py -v
python tools/build_sender_html.py --check
```

Document the new architecture, migration path, hardware validation checklist, and release rules. Update `README.md` so it reflects the refactored architecture instead of the transitional one.

**Step 4: Run test to verify it passes**

Run: `pytest -v`
Expected: PASS on the non-hardware suite

Run: `powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/architecture.md docs/migration.md .github/workflows/ci.yml tools/run_quality_gate.ps1 README.md docs/testing.md docs/hardware-setup.md pyproject.toml
git commit -m "docs: finalize refactor architecture and quality gates"
```

## Manual Validation Checklist

- Launch `hdmi-web` and verify `/`, `/sender`, `/history`, and `/settings` load.
- Start idle preview in the web UI and verify preview still works before a receive session starts.
- Start a sequential receive session from the web UI and confirm the same progress model as the CLI path.
- Start a fountain receive session from the web UI and confirm completion event, saved file metadata, and file actions still work.
- Run a browser sender transfer using generated `sender.html`.
- Run a Python sender transfer using `hdmi-send`.
- Confirm both sender paths can talk to the same receiver implementation.
- Re-run a one-PC loopback test on `balanced` before enabling `speed`.

## Final Exit Checklist

- No protocol constants are duplicated manually between Python and browser source.
- No receive state machine logic lives in `receiver_worker.py` or Flask route code.
- No send state machine logic lives in `sender/cli/send.py` or browser UI code.
- Capture lifecycle is owned by one adapter, not by route code.
- Fountain overhead targets are enforced by tests and reflected in documentation.
- All legacy modules are either deleted or marked as explicit compatibility shims.
- README, testing docs, and hardware docs describe the new architecture instead of the migration state.

