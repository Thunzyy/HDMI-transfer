---
phase: 01-test-foundation
plan: 01
subsystem: testing
tags: [pytest, sequential-encode, round-trip, conftest, hardware-markers]

# Dependency graph
requires: []
provides:
  - "pytest infrastructure (conftest.py, pytest.ini, requirements-dev.txt)"
  - "Hardware marker system with --hardware CLI flag"
  - "Fixed test_loopback.py with correct encode_frame/decode_frame signatures"
  - "8 in-memory sequential round-trip tests proving encode/decode correctness"
  - "Git tag v0.1-working-prototype as rollback point"
affects:
  - 01-test-foundation (all subsequent plans depend on pytest infra)
  - 02-protocol (sequential tests validate encode/decode before refactoring)

# Tech tracking
tech-stack:
  added: [pytest, hypothesis, opencv-python-headless, numpy]
  patterns: [in-memory round-trip testing, hardware marker skip, conftest path setup]

key-files:
  created:
    - tests/conftest.py
    - pytest.ini
    - requirements-dev.txt
    - tests/test_sequential.py
  modified:
    - tests/test_loopback.py

key-decisions:
  - "ctypes.wintypes imports fine on Linux -- no sender.py patching needed"
  - "Empty data encode/decode returns (None, None, None, None) -- tested as edge case"

patterns-established:
  - "In-memory round-trip: encode_frame -> sample_frame -> decode_frame without hardware"
  - "Hardware tests skipped by default via @pytest.mark.hardware + conftest skip logic"
  - "Test classes grouped by concern: SingleFrame, MultiFrame, MetadataPreservation, EdgeCases"

# Metrics
duration: 2min
completed: 2026-02-16
---

# Phase 1 Plan 1: Test Infrastructure and Sequential Tests Summary

**Pytest infrastructure with hardware markers, fixed loopback test signatures, and 8 in-memory sequential encode/decode round-trip tests proving bit-perfect correctness**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-16T09:06:50Z
- **Completed:** 2026-02-16T09:09:02Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Established pytest infrastructure: conftest.py with sys.path setup, --hardware CLI flag, hardware marker skip logic; pytest.ini with strict markers; requirements-dev.txt pinning all dev dependencies
- Fixed TEST-01 bug in test_loopback.py: corrected encode_frame to 3 args and decode_frame to 4 return values, added @pytest.mark.hardware, switched to tmp_path, replaced print-assertions with proper assert
- Created 8 comprehensive sequential round-trip tests covering: full/partial single-frame, multi-frame reassembly, index/total preservation, empty data rejection, all-zeros, all-ones
- Created git tag v0.1-working-prototype on pre-change HEAD as rollback point

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test infrastructure and tag prototype** - `636a89c` (chore)
2. **Task 2: Fix test_loopback.py and create test_sequential.py** - `71a7a19` (test)

## Files Created/Modified
- `tests/conftest.py` - sys.path setup, --hardware CLI option, hardware marker registration and skip logic
- `pytest.ini` - Test discovery config with strict markers
- `requirements-dev.txt` - Dev dependency pinning (pytest, hypothesis, opencv-python-headless, numpy)
- `tests/test_sequential.py` - 8 in-memory sequential encode/decode round-trip tests
- `tests/test_loopback.py` - Fixed function signatures, hardware marker, tmp_path, proper assertions

## Decisions Made
- ctypes.wintypes imports successfully on this Linux system, so no sender.py patching or monkeypatching was needed for imports
- Kept encode_frame stdout noise in tests (no production code changes) as the plan specified
- Used test classes to group related tests by concern rather than flat functions

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed without issues. The Linux ctypes.wintypes concern from the research turned out to be a non-issue.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- pytest infrastructure fully operational for all subsequent 01-test-foundation plans
- Sequential encode/decode correctness proven with in-memory tests
- Hardware tests properly gated behind --hardware flag
- Ready for plan 01-02 (fountain codec tests) and beyond

---
*Phase: 01-test-foundation*
*Completed: 2026-02-16*
