# Sender-PC Profiles and Auto Receive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Named sender-PC profiles with their own calibration, plus a receiver-wide auto receive that arms and re-arms the receiver without clicking Start.

**Architecture:** A SQLite `ProfileStore` on the receiver holds profiles and two state values (active profile, auto switch). The calibration cache key gains an optional sender profile; the worker tries the active profile's hint, then other matching profiles' hints, then full calibration. An `AutoReceiveSupervisor` thread starts workers through the same function as `/api/receive/start` and decides re-arm or pause from how each worker ended.

**Tech Stack:** Python 3.11, Flask, sqlite3, OpenCV (existing), vanilla JS in `src/web/static`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-26-receiver-profiles-auto-design.md` (read its "Decisions after the builder check" first: they override earlier lines).

## Global Constraints

- State files live in `HDMI_TRANSFER_STATE_DIR` (default `~/.hdmi-transfer`), like `calibration.json` and `history.sqlite3`.
- Stores are best effort: a broken database logs and never raises into a transfer.
- No profile selected = exactly today's behaviour, including identical calibration keys.
- Allowed values: profile in `PROFILES` keys, mode in `fountain|sequential|auto`, bpc in `1|2|3`, preview quality in `45|60|75|90`.
- Auto receive: only `complete` re-arms (after 1.0 s); 3 consecutive failures pause; manual Stop pauses; pause clears on switch off/on, profile activation, or manual Start; pause is in memory only.
- UI copy: sentence case, no em dash, components from `shared.css` (`ui-btn`, `ui-field`, `ui-badge`, `icon-btn`, `help-tip`).

## Review Focus

1. Deleting the active profile while auto receive is armed: supervisor must stop arming (no profile = no auto).
2. Two profiles with the same name, or an empty name: API returns 400, store never has duplicates.
3. Capture device unplugged while auto is on: worker ends without `complete` each time, so it pauses after 3, not an endless loop.
4. Server restart with auto on and the saved device index now pointing to another card: arm by `device_name` first, index only as fallback.
5. A manual Start while auto is armed replaces the armed worker: must not count as a failure.

---

### Task 1: ProfileStore

**Files:**
- Create: `src/adapters/profile_store.py`
- Test: `tests/test_profile_store.py`

**Interfaces:**
- Produces: `class ProfileStore(path: str | Path | None = None)` with
  - `list() -> list[dict]` (keys: `id, name, device_name, device_index, profile, mode, bpc, preview_quality, created_at, updated_at`), ordered by `updated_at` desc
  - `get(profile_id: int) -> dict | None`
  - `create(data: dict) -> dict` and `update(profile_id: int, data: dict) -> dict | None`, both raise `ProfileError(message)` on invalid or duplicate name
  - `delete(profile_id: int) -> bool` (clears `active_profile_id` if it was active)
  - `get_active_id() -> int | None`, `set_active_id(profile_id: int | None) -> None` (raises `ProfileError` for unknown id)
  - `get_auto_receive() -> bool`, `set_auto_receive(enabled: bool) -> None`
  - `matching_profile_ids(profile_id: int) -> list[int]`: other profiles with the same `device_name` and `profile`, most recently updated first
- Schema per spec (`profiles` without `auto_receive`, `state(key, value)`).

- [ ] **Step 1: Write failing tests**: `test_create_list_get_roundtrip`, `test_name_is_required_and_unique` (empty, whitespace, duplicate case-insensitive -> `ProfileError`), `test_invalid_values_rejected` (profile `"x"`, mode `"fast"`, bpc 4, preview 50), `test_update_changes_updated_at_and_fields`, `test_delete_active_clears_active`, `test_auto_receive_flag_persists_across_instances`, `test_matching_profile_ids_same_device_and_profile_only`, `test_corrupt_database_does_not_raise` (write garbage bytes to the file; `list()` returns `[]`, `get_auto_receive()` returns `False`).
- [ ] **Step 2:** `uv run --no-sync pytest tests/test_profile_store.py -q` -> FAIL (module missing).
- [ ] **Step 3:** Implement following `history_store.py` patterns (lock, connect per call, `CREATE TABLE IF NOT EXISTS`, catch `sqlite3.DatabaseError` and log). Validation raises `ProfileError` before touching the DB.
- [ ] **Step 4:** Same command -> PASS.
- [ ] **Step 5:** Commit `feat(profiles): store sender-PC profiles in SQLite`.

### Task 2: Calibration keyed by sender profile

**Files:**
- Modify: `src/adapters/calibration_store.py`
- Test: `tests/test_calibration_store.py`

**Interfaces:**
- Produces: `calibration_key(..., sender_profile: int | None = None) -> str` (when `None`, the hashed context dict is byte-identical to today's; when set, add `"sender_profile": id`).
- `CalibrationStore.save(key, sampling, *, sender_profile: int | None = None) -> bool` stores `"sender_profile"` in the entry when given.
- `CalibrationStore.delete_profile(sender_profile: int) -> int` removes entries with that id, returns count. `_VERSION` stays 1.

- [ ] **Step 1: Failing tests**: `test_key_without_profile_is_unchanged` (compare with a literal hash computed from today's code before editing), `test_key_differs_per_profile`, `test_delete_profile_removes_only_its_entries`.
- [ ] **Step 2:** run -> FAIL. **Step 3:** implement. **Step 4:** run `tests/test_calibration_store.py tests/test_receiver_calibration.py` -> PASS.
- [ ] **Step 5:** Commit `feat(calibration): scope cached geometry to a sender profile`.

### Task 3: Worker hint order and profile match

**Files:**
- Modify: `src/adapters/receive_worker.py` (`__init__`, `stop`, `_wait_for_preflight`, `_mirror_runtime_state`)
- Test: `tests/test_receiver_calibration.py`

**Interfaces:**
- Consumes: Task 2 `calibration_key(sender_profile=...)`, `save(..., sender_profile=...)`.
- Produces: `ReceiverWorker(..., sender_profile_id: int | None = None, fallback_profile_ids: list[int] | None = None)`;
  `stop(reason: str = "user")` sets `self.stop_reason` (`"user" | "supervisor" | "replaced"`) before stopping;
  runtime state gains `sender_profile_id` and `matched_profile_id` (set when a fallback profile's hint validated);
  `status` event at `preflight_ok` includes `matched_profile_id`.
- Algorithm (replaces the single `hints[key]` lookup): for each bpc probe candidate, build the ordered candidate list `[(active_id, hint), (fallback_id, hint)...]` with hints loaded from each profile's key, skipping `None` hints; with `force_recalibration`, the list is empty. Try candidates as the starting sampling in order, the same way `hints[key]` is tried today; if none validates within the existing flow, the existing full search runs. On success save under the key of the profile that matched (`sender_profile=` that id), and set `matched_profile_id` only when it differs from `sender_profile_id`.

- [ ] **Step 1: Failing tests** (reuse `FiniteCapture`, letterboxed frames from `test_letterboxed_geometry_is_learned_then_reused_without_search`):
  - `test_profile_hint_is_used_and_saved_under_profile`: worker(sender_profile_id=1) learns letterbox; store has entry under `key(sender_profile=1)`, none under `key()`.
  - `test_fallback_profile_hint_matches_and_is_reported`: save letterbox sampling under `key(sender_profile=2)`; worker(sender_profile_id=1, fallback_profile_ids=[2]); monkeypatch `estimate_sampling_from_frame` to fail; preflight succeeds; `get_runtime_state()["matched_profile_id"] == 2`.
  - `test_no_profile_hint_falls_back_to_full_calibration`: fallback ids with no saved entries; preflight succeeds; saved under profile 1.
  - `test_stop_reason_defaults_to_user`.
- [ ] **Step 2:** run -> FAIL. **Step 3:** implement. **Step 4:** `uv run --no-sync pytest tests/test_receiver_calibration.py tests/test_receiver_worker_sequential.py -q` -> PASS.
- [ ] **Step 5:** Commit `feat(receiver): try other sender profiles' calibration before recalibrating`.

### Task 4: Shared start function and auto receive supervisor

**Files:**
- Create: `src/application/auto_receive.py`
- Modify: `src/interfaces/web/routes_receive.py` (extract start body)
- Test: `tests/test_auto_receive.py`

**Interfaces:**
- Produces in `routes_receive.py`: `start_receiver_worker(app, settings: dict, *, force_recalibration: bool = False, profile_id: int | None = None) -> ReceiverWorker` (raises `ValueError` for unknown profile name). It stops an alive worker with `stop(reason="replaced")`, resolves fallback ids with `app._profile_store.matching_profile_ids(profile_id)` when `profile_id` is set, and passes `sender_profile_id`/`fallback_profile_ids`. `/api/receive/start` calls it, accepts optional `profile_id`, and calls `app._auto_receive.clear_pause()`. `/api/receive/stop` uses `stop(reason="user")` then `app._auto_receive.pause("Stopped by user")`.
- Produces in `auto_receive.py`: `class AutoReceiveSupervisor(store: ProfileStore, start_worker: Callable[[dict], object], get_worker: Callable[[], object | None], *, rearm_delay_s: float = 1.0, max_failures: int = 3, clock=time.monotonic)` with
  - `tick() -> None` (one decision step; the thread calls it every 0.5 s)
  - `start() / shutdown()` (daemon thread)
  - `pause(reason: str)`, `clear_pause()`, `status() -> dict` (`enabled, paused, reason, consecutive_failures, armed`)
  - `on_profile_changed()` (clears pause; stops an armed idle worker with `stop(reason="supervisor")` so the next tick re-arms with new settings)
- `tick` rules: no-op if switch off, paused, or no active profile. If no alive worker: look at the last worker it started (if any) -> `state == "complete"` resets failures and re-arms after `rearm_delay_s`; `stop_reason in {"supervisor","replaced"}` is neutral; anything else counts a failure; at `max_failures` call `pause("3 receptions failed in a row")`. Then start a worker with the active profile's settings (`device` resolved by `device_name` through `app._device_registry.list_devices()`, else `device_index`).

- [ ] **Step 1: Failing tests** with a `FakeWorker(state, stop_reason=None, alive=False)` and a fake clock:
  `test_arms_when_enabled_with_active_profile`, `test_does_nothing_when_disabled_or_no_profile`, `test_rearms_after_complete_only_after_delay`, `test_pauses_after_three_failures`, `test_success_resets_failure_count`, `test_replaced_and_supervisor_stops_are_neutral`, `test_manual_pause_and_clear`, `test_deleted_active_profile_stops_arming`.
- [ ] **Step 2:** run -> FAIL. **Step 3:** implement both files. **Step 4:** `uv run --no-sync pytest tests/test_auto_receive.py tests/test_web_app_factory.py -q` -> PASS.
- [ ] **Step 5:** Commit `feat(receiver): auto receive supervisor`.

### Task 5: Profiles and auto HTTP API, app wiring

**Files:**
- Create: `src/interfaces/web/routes_profiles.py`
- Modify: `src/interfaces/web/app_factory.py`, `src/interfaces/web/routes_receive.py` (status fields)
- Test: `tests/test_web_profiles_api.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4.
- Routes per spec: `GET/POST /api/profiles`, `PUT/DELETE /api/profiles/<int:id>`, `POST /api/profiles/<int:id>/activate`, `GET/POST /api/receive/auto` (`{"enabled": bool}`). Errors: `ProfileError` -> 400 `{"error": msg}`, unknown id -> 404. Delete also calls `CalibrationStore().delete_profile(id)`. Activate and update of the active profile call `app._auto_receive.on_profile_changed()`. Turning auto on calls `clear_pause()`.
- `create_app`: `app._profile_store = ProfileStore()`; `app._auto_receive = AutoReceiveSupervisor(...)` always; `.start()` only when `runtime=True`. `shutdown_runtime` calls `app._auto_receive.shutdown()` first.
- `/api/receive/status` adds `active_profile_id`, `auto_receive` (the `status()` dict), `matched_profile_id` from the worker state. When a worker reports `matched_profile_id`, the status route and the supervisor set it active (`set_active_id`).

- [ ] **Step 1: Failing tests** (runtime=False client, `HDMI_TRANSFER_STATE_DIR` to `tmp_path` via monkeypatch): `test_profile_crud_roundtrip`, `test_duplicate_name_returns_400`, `test_unknown_profile_returns_404`, `test_activate_sets_active_and_status_reports_it`, `test_auto_toggle_roundtrip`, `test_delete_active_profile_clears_active`.
- [ ] **Step 2-4:** FAIL -> implement -> `uv run --no-sync pytest tests/test_web_profiles_api.py tests/test_web_app_factory.py -q` PASS.
- [ ] **Step 5:** Commit `feat(web): profiles and auto receive API`.

### Task 6: Receive and Settings UI

**Files:**
- Modify: `src/web/static/receiver.html`, `src/web/static/settings.html`, `src/web/static/shared.css` (switch component only)
- Test: `tests/test_web_static_defaults.py` (markup ids present)

**Interfaces:**
- Consumes: Task 5 routes.
- Receive sidebar, above "Capture": `<select id="senderProfileSelect">` ("No profile" + profiles), `<button role="switch" id="autoReceiveSwitch" aria-checked>` labelled "Auto receive", status text `#autoReceiveStatus` ("Armed, waiting for the sender" / "Paused: <reason>" / "Off"). Selecting a profile: POST activate, fill Device/Profile/Mode/Encoding/Preview from it. Changing those controls with a profile active: PUT the profile (immediate save, spec decision 2). When auto is on, the page polls `/api/receive/status` every 2 s and, when a worker is active and no SSE is open, attaches via the existing `checkActiveWorker()` path so progress shows without Start. When `matched_profile_id` differs from the selected profile: switch the select and log "Signal matched <name>, switched profile".
- Settings: new full-width card "Sender PCs" above the other groups: table of profiles (name, device, profile, encoding) with `icon-btn` edit and delete; "Add sender PC" `ui-btn` opens an inline form (name + same five fields); delete uses a confirm dialog like History; empty state copy from spec.
- `.ui-switch` in `shared.css`: 32x18 track, accent when `aria-checked="true"`, focus ring, 44px hit area under 760px.

- [ ] **Step 1: Failing test** `test_receiver_exposes_profile_and_auto_controls` (asserts `id="senderProfileSelect"`, `id="autoReceiveSwitch"`, `role="switch"` in `/`; `id="senderProfiles"` in `/settings`).
- [ ] **Step 2-4:** FAIL -> implement -> PASS.
- [ ] **Step 5: Browser check** on the running app (`preview_start hdmi-web`): create "PC BNP" and "PC PERSO" in Settings, select one in Receive (fields fill), toggle auto (status shows Armed, Start disabled while armed), Stop shows Paused, delete a profile with confirm, 375px layout has no page overflow, console clean.
- [ ] **Step 6:** Commit `feat(ui): sender PC profiles and auto receive switch`.

### Task 7: Verify and ship

- [ ] `uv run --no-sync pytest -q --ignore=tests/perf` -> all pass; `uv run --no-sync pytest tests/browser --browser -q` -> pass; `uv run --no-sync python tools/build_sender_html.py --check` -> up to date.
- [ ] Antislop delivery gate on the new UI; whole-branch review by a fresh reviewer.
- [ ] Update `docs/calibration.md` with a short "Sender PC profiles" section.
- [ ] Push `feat/receiver-profiles-auto`, open PR with base `feat/supabase-ui-redesign` (stacked on PR #21).
