---
phase: "06"
plan: "03"
subsystem: "cli"
tags: ["profile-flag", "progress-tracker", "cli-ux", "speed-eta", "resolution-profiles"]
depends_on:
  requires: ["06-01"]
  provides: ["--profile CLI flag on sender/receiver", "ProgressTracker class", "profile-wired CLI layer"]
  affects: ["06-04"]
tech_stack:
  added: []
  patterns: ["profile threading through CLI layer", "real-time progress tracking with warmup"]
key_files:
  created:
    - "src/hdmi_exfil/cli/progress.py"
  modified:
    - "src/hdmi_exfil/cli/send.py"
    - "src/hdmi_exfil/cli/receive.py"
decisions:
  - id: "06-03-fps-override"
    description: "--fps default changed from 240 to None; overrides profile target_fps when explicitly set"
  - id: "06-03-fountain-tracker"
    description: "Fountain path uses manual speed/ETA computation (not ProgressTracker.update) since decoder.chunks is authoritative for progress"
  - id: "06-03-warmup"
    description: "2-second warmup before ETA estimation; shows --:-- during warmup period"
metrics:
  duration: "6min"
  completed: "2026-02-17"
  tests_before: 286
  tests_after: 296
---

# Phase 6 Plan 3: CLI Profile Flags and Progress Reporting Summary

**One-liner:** --profile speed|balanced|quality wired to both sender/receiver CLIs, ProgressTracker class for real-time speed (KB/s) and ETA on receiver, all module-level constants replaced with profile-based access.

## What Was Done

### Task 1: ProgressTracker Class + Sender --profile Flag

**Created `src/hdmi_exfil/cli/progress.py`:**
- `ProgressTracker` class with `total_items`, `total_bytes`, 2-second warmup
- `update(items, bytes_count)` increments counters
- Properties: `progress_pct`, `speed_bytes_per_sec`, `eta_seconds`
- `format_line(extra)` returns carriage-return-prefixed progress string
- `_format_eta(seconds)` static method for "m:ss" or "--:--" formatting
- Only stdlib imports (`time`)

**Updated `src/hdmi_exfil/cli/send.py`:**
- Added `--profile` argument with choices `speed|balanced|quality`
- Changed `--fps` default from `240` to `None` (profile provides default)
- `--fps` overrides profile's `target_fps` when both specified
- `get_protocol(args.mode, profile=profile)` forwards profile to constructor
- `_solid_frame()` accepts profile parameter for resolution
- `_show_pause_screen()` and `_show_end_screen()` accept profile
- `_send_sequential()` uses `profile.seq_bytes_per_frame` for chunk slicing
- `_send_fountain()` uses `profile.fount_bytes_per_frame` for payload size
- `PygameRenderer` created with `width=profile.width, height=profile.height`
- Calibration frame uses profile resolution
- All `WIDTH/HEIGHT/BLOCK_SIZE/BYTES_PER_FRAME` imports removed
- `FOUNTAIN_PAYLOAD_SIZE` import from fountain.py removed

### Task 2: Receiver --profile Flag + Profile Wiring

**Updated `src/hdmi_exfil/cli/receive.py`:**
- Added `--profile` argument (same as sender)
- `CaptureSource` created with `width=profile.width, height=profile.height, fps=profile.target_fps`
- All receive functions (`_receive_sequential`, `_receive_fountain`, `_receive_auto`, `_run_receiver`) accept `profile: ResolutionProfile` parameter
- `sample_frame()` calls use `profile.rows, profile.cols, profile.block_size`
- Frame resize checks use `profile.height` and `profile.width`
- `_draw_grid_overlay()` parameterized with rows/cols/block_size/width/height
- `_finalize_sequential()` accepts `bytes_per_frame` keyword argument
- `get_protocol()` called with `profile=profile` in all receiver paths
- All `WIDTH/HEIGHT/ROWS/COLS/BYTES_PER_FRAME/BLOCK_SIZE` imports removed
- Only `FRAME_TYPE_DATA/END/START` retained as protocol constants

### Task 3: ProgressTracker Integration into Receiver

- Sequential path: `ProgressTracker` created after START frame with total_frames and file_size, `tracker.update(1, len(data))` on each DATA frame, `tracker.format_line(capture_fps_str)` replaces manual progress string
- Fountain path: Manual speed/ETA computation using `time.perf_counter_ns()` with 2-second warmup guard, `ProgressTracker._format_eta()` for consistent formatting
- Both paths display "--:--" during the first 2 seconds (warmup period)
- Capture FPS string appended to progress lines in both paths

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| --fps default changed to None | Enables detection of explicit override vs. profile default |
| Fountain uses manual speed/ETA, not ProgressTracker.update | decoder.chunks is authoritative for progress; byte counting is separate from chunk recovery |
| 2-second warmup for ETA | Prevents wildly inaccurate ETA during initial frames |

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

- Before: 286 passed, 3 deselected
- After: 296 passed, 3 deselected (hypothesis property tests generated more examples)
- Zero regressions

## Next Phase Readiness

Plan 06-03 completes the CLI profile wiring. For 06-04:
- Both sender and receiver support `--profile speed|balanced|quality`
- Default behavior (no --profile) is identical to previous code (DEFAULT_PROFILE = speed = 1080p@240fps)
- Profile values flow through to all encoding/decoding/display operations
