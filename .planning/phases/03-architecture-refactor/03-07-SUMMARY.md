---
phase: 03-architecture-refactor
plan: 07
subsystem: testing
tags: [pytest, imports, package-migration, conftest, test-suite]

# Dependency graph
requires:
  - phase: 03-03
    provides: SequentialProtocol with encode/decode/legacy methods
  - phase: 03-04
    provides: FountainProtocol, FountainDecoder, PRNG in hdmi_exfil.prng
  - phase: 03-06
    provides: CLI wiring and build script proving package structure works
provides:
  - All 59 tests import exclusively from hdmi_exfil.* package
  - Clean conftest.py with no sys.path hack
  - Pytest config consolidated in pyproject.toml (pytest.ini removed)
  - Phase 3 architecture refactor functionally complete
affects: [04-performance, 05-fountain-encode, 06-ux]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Protocol instance at module level (_proto = SequentialProtocol()) for test helpers"
    - "sample_frame called with explicit ROWS/COLS/BLOCK_SIZE params (no config dependency in sampler)"
    - "decode_frame_legacy for 4-tuple backward compat, decode_frame for FrameResult"
    - "route_frame re-implemented as local test helper using package constants"

key-files:
  modified:
    - tests/conftest.py
    - tests/test_sequential.py
    - tests/test_fountain.py
    - tests/test_prng.py
    - tests/test_properties.py
    - tests/test_loopback.py
  deleted:
    - pytest.ini

key-decisions:
  - "route_frame re-implemented inline in test_sequential.py rather than adding to package (test-only concern)"
  - "choose_indices wrapper converts frozenset->set for test helper compatibility"
  - "FOUNTAIN_PAYLOAD_SIZE aliased from package PAYLOAD_SIZE constant (single source of truth)"

patterns-established:
  - "All test imports use from hdmi_exfil.* pattern exclusively"
  - "SequentialProtocol instance used for encode/decode instead of free functions"
  - "sample_frame always called with explicit grid params (ROWS, COLS, BLOCK_SIZE)"

# Metrics
duration: 4min
completed: 2026-02-16
---

# Phase 3 Plan 7: Test Migration Summary

**All 59 tests migrated to hdmi_exfil package imports -- zero references to old flat modules, conftest cleaned, pytest.ini removed**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-16T14:19:10Z
- **Completed:** 2026-02-16T14:23:10Z
- **Tasks:** 2
- **Files modified:** 7 (5 modified, 1 deleted, 1 rewritten)

## Accomplishments
- Migrated all 5 test files to import from hdmi_exfil.* package exclusively
- Removed sys.path.insert hack from conftest.py
- Deleted pytest.ini (config consolidated in pyproject.toml [tool.pytest.ini_options])
- All 58 tests pass, 1 hardware test correctly skips (59 collected total)
- Tests verified with both default and --import-mode=importlib

## Task Commits

Each task was committed atomically:

1. **Task 1: Update conftest.py and remove pytest.ini** - `2e281bb` (chore)
2. **Task 2: Migrate all test file imports** - `c6f01f4` (feat)

## Files Created/Modified
- `tests/conftest.py` - Cleaned: removed sys.path hack, kept hardware marker support
- `tests/test_sequential.py` - Migrated to SequentialProtocol, sample_frame with explicit params, inline route_frame
- `tests/test_fountain.py` - Migrated to hdmi_exfil.prng.PRNG/choose_indices, FountainDecoder from package
- `tests/test_prng.py` - Migrated to hdmi_exfil.prng.PRNG/choose_indices
- `tests/test_properties.py` - Migrated to SequentialProtocol/FountainDecoder/sample_frame from package
- `tests/test_loopback.py` - Migrated to SequentialProtocol/sample_frame from package
- `pytest.ini` - Deleted (config now in pyproject.toml)

## Decisions Made
- **route_frame as test helper:** Re-implemented route_frame as a local `_route_frame` function in test_sequential.py rather than adding it to the package. It's a test-only concern that verifies raw byte routing; the package uses protocol instances directly.
- **choose_indices frozenset wrapping:** The package's choose_indices returns frozenset (hashable for caching). Test helpers that need mutable sets use `set(choose_indices(...))` wrapper.
- **FOUNTAIN_PAYLOAD_SIZE aliasing:** test_fountain.py aliases `PAYLOAD_SIZE` from `hdmi_exfil.protocols.fountain` as `FOUNTAIN_PAYLOAD_SIZE` for readability, keeping a single source of truth.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all migrations were straightforward. The new package API (SequentialProtocol instance methods, explicit sampler params) mapped cleanly to existing test patterns.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 3 architecture refactor is functionally complete
- All code runs through the hdmi_exfil package; old flat modules remain but are no longer used by tests
- Test suite validates the entire refactored architecture end-to-end
- Ready for Phase 4 (performance optimization) with clean package structure

---
*Phase: 03-architecture-refactor*
*Completed: 2026-02-16*
