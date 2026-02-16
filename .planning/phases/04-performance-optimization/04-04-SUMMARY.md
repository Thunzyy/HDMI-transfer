---
phase: 04-performance-optimization
plan: 04
subsystem: capture
tags: [threading, deque, ring-buffer, fps, perf_counter_ns, daemon-thread]

# Dependency graph
requires:
  - phase: 03-architecture-refactor
    provides: CaptureSource with context manager and duck-typed read() interface
provides:
  - ThreadedCapture wrapper decoupling capture I/O from main processing thread
  - FPSReporter sliding-window FPS measurement utility
  - Ring buffer (deque maxlen) auto-discarding stale frames
affects: [04-05-wire-cli, 05-fountain-optimization, 06-ux-polish]

# Tech tracking
tech-stack:
  added: []
  patterns: [daemon-thread-capture, deque-ring-buffer, sliding-window-fps]

key-files:
  created:
    - src/hdmi_exfil/capture/threaded.py
    - tests/test_threaded_capture.py
  modified: []

key-decisions:
  - "ThreadedCapture uses duck typing (no CaptureSource import) -- wraps any object with read()->(bool, frame)"
  - "Default buffer_size=16 (~96MB at 1080p) balances latency vs memory"
  - "FPSReporter uses perf_counter_ns for nanosecond-precision monotonic timing"
  - "actual_fps returns 0.0 when window is stale (>2s) to avoid misleading numbers"

patterns-established:
  - "Daemon thread capture: background thread fills deque, main thread popleft non-blocking"
  - "FPSReporter tick() pattern: call per frame, returns FPS on interval or None"

# Metrics
duration: 2min
completed: 2026-02-16
---

# Phase 4 Plan 4: Threaded Capture Summary

**Background daemon-thread capture with deque ring buffer and sliding-window FPS reporting using perf_counter_ns**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-16T22:39:38Z
- **Completed:** 2026-02-16T22:41:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- ThreadedCapture wraps any read()-compatible source in a daemon thread with bounded deque ring buffer
- Non-blocking read() returns (False, None) when buffer empty -- no main thread stalls
- FPSReporter measures actual capture FPS over configurable sliding windows
- Context manager protocol (start on enter, stop on exit) for clean lifecycle
- 10 comprehensive unit tests covering frame production, buffer bounds, context manager, and edge cases

## Task Commits

Each task was committed atomically:

1. **Task 1: Create threaded.py with ThreadedCapture and FPSReporter** - `b7b13db` (feat)
2. **Task 2: Add ThreadedCapture and FPSReporter unit tests** - `08d7867` (test)

## Files Created/Modified
- `src/hdmi_exfil/capture/threaded.py` - ThreadedCapture wrapper and FPSReporter utility (157 lines)
- `tests/test_threaded_capture.py` - Unit tests with MockSource, 10 test cases (155 lines)

## Decisions Made
- ThreadedCapture uses duck typing -- does not import CaptureSource, accepts any object with `.read() -> (bool, frame)`. This keeps the module dependency-free and testable with simple mocks.
- Default buffer_size=16 frames (~96MB at 1080p). Provides ~67ms buffering at 240fps without excessive memory. Configurable via constructor parameter.
- FPSReporter uses `time.perf_counter_ns()` for nanosecond-precision monotonic timing (no float drift).
- `actual_fps` property returns 0.0 when measurement window is stale (>2 seconds) to avoid reporting misleading stale numbers.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ThreadedCapture ready for integration into CLI receive pipeline (04-05)
- FPSReporter ready for real-time throughput display in receiver
- All 72 existing tests still pass (no regressions)

---
*Phase: 04-performance-optimization*
*Completed: 2026-02-16*
