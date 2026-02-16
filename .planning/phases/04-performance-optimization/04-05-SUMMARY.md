---
phase: 04-performance-optimization
plan: 05
subsystem: cli
tags: [pygame-ce, numba, threaded-capture, fps-reporting, cli-integration, xor-into]

# Dependency graph
requires:
  - phase: 04-01
    provides: "3bpp fountain encoding with PAYLOAD_SIZE=12138"
  - phase: 04-02
    provides: "Numba @njit xor_into and warmup() for JIT pre-compilation"
  - phase: 04-03
    provides: "PygameRenderer with SDL2 vsync-locked fullscreen display"
  - phase: 04-04
    provides: "ThreadedCapture with ring buffer and FPSReporter"
provides:
  - "hdmi-send with --renderer pygame/cv2 flag and Numba-accelerated fountain XOR"
  - "hdmi-recv with --threaded/--no-threaded flags, ring buffer, and FPS reporting"
  - "All Phase 4 performance components wired into user-facing CLI entry points"
affects: [05-fountain-optimization, 06-ux-polish]

# Tech tracking
tech-stack:
  added: []
  patterns: ["renderer-factory pattern with flag-based selection", "threaded-capture wrapping with fallback to direct reads"]

key-files:
  modified:
    - src/hdmi_exfil/cli/send.py
    - src/hdmi_exfil/cli/receive.py

key-decisions:
  - "Pause/end screens use solid-color numpy frames (no cv2.putText) for renderer-agnostic operation"
  - "Fountain chunks stored as np.ndarray list (not bytearray) for Numba xor_into compatibility"
  - "Receive loops use time.sleep(0.001) on empty buffer to avoid CPU spin with ThreadedCapture"
  - "FPS reporting at 2-second intervals appended to existing progress lines"
  - "_run_receiver helper extracts mode dispatch to avoid duplicating threaded/direct paths"

patterns-established:
  - "Renderer factory: --renderer flag selects PygameRenderer or FrameRenderer with renderer_cls(**kwargs)"
  - "Threaded capture wrapping: CaptureSource opened first, then optionally wrapped in ThreadedCapture"
  - "FPSReporter integrated into receive loops for real-time capture throughput visibility"

# Metrics
duration: 4min
completed: 2026-02-16
---

# Phase 4 Plan 5: CLI Integration of Performance Components Summary

**PygameRenderer, Numba XOR, ThreadedCapture, and FPS reporting wired into hdmi-send and hdmi-recv CLI entry points with flag-based selection**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-16T22:51:45Z
- **Completed:** 2026-02-16T22:55:22Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- hdmi-send now uses PygameRenderer by default (SDL2 vsync) with --renderer cv2 fallback
- Fountain send loop uses numpy arrays + Numba xor_into instead of Python byte-by-byte XOR
- Numba JIT warmup happens during calibration screen (before data transfer starts)
- hdmi-recv wraps CaptureSource in ThreadedCapture by default with configurable ring buffer
- Real-time capture FPS reported during both sequential and fountain reception
- All 84 tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire PygameRenderer and Numba XOR into send.py** - `1045e8a` (feat)
2. **Task 2: Wire ThreadedCapture and FPS reporting into receive.py** - `240c51e` (feat)

## Files Created/Modified
- `src/hdmi_exfil/cli/send.py` - Added --renderer flag, PygameRenderer selection, Numba xor_into in fountain loop, warmup during calibration, solid-color pause/end screens
- `src/hdmi_exfil/cli/receive.py` - Added --threaded/--no-threaded/--buffer-size flags, ThreadedCapture wrapping, FPSReporter in receive loops, _run_receiver helper, capture stats printing

## Decisions Made
- Pause/end screens converted from cv2.putText overlays to solid-color numpy arrays (orange=pause, green=done, red=interrupted). This ensures both PygameRenderer and FrameRenderer work without cv2 drawing dependencies. Status text goes to terminal via print().
- Fountain chunks stored as `list[np.ndarray]` instead of `list[bytes]` so xor_into can operate directly without conversion at each XOR step.
- ThreadedCapture wrapping uses nested context managers: `with cap: with ThreadedCapture(cap): ...` ensuring both the underlying source and the thread are properly cleaned up.
- FPS reporting uses 2-second intervals (not 1s) to avoid too-frequent updates that compete with progress output.
- Auto-detect comment updated from "1-bit encoding" to "3-bit encoding" since both protocols now use 3bpp.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 4 (Performance Optimization) is now complete: all 5 plans executed
- hdmi-send and hdmi-recv use all performance components by default
- Users get PygameRenderer (vsync), Numba XOR (JIT), 3bpp encoding (3x capacity), and ThreadedCapture (non-blocking) just by running the standard CLI commands
- Ready for Phase 5 (Fountain Code Optimization) which will tune the degree distribution and add Gaussian elimination fallback

---
*Phase: 04-performance-optimization*
*Completed: 2026-02-16*
