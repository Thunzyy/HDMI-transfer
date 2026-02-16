---
phase: 03-architecture-refactor
plan: 01
subsystem: infra
tags: [setuptools, pyproject, src-layout, importlib-resources, packaging]

requires:
  - phase: 02-protocol-foundation
    provides: common.py constants that config.py must match exactly
provides:
  - Installable hdmi_exfil package via pip install -e .
  - constants.json single source of truth for encoding parameters
  - config.py module exposing all derived constants (WIDTH, BYTES_PER_FRAME, etc.)
  - Package directory structure for protocols/, capture/, display/, file_handling/, cli/
affects: [03-02, 03-03, 03-04, 03-05, 03-06, 03-07]

tech-stack:
  added: [setuptools, importlib.resources]
  patterns: [src-layout packaging, JSON constants with Python loader]

key-files:
  created:
    - pyproject.toml
    - src/hdmi_exfil/__init__.py
    - src/hdmi_exfil/constants.json
    - src/hdmi_exfil/config.py
    - src/hdmi_exfil/protocols/__init__.py
    - src/hdmi_exfil/capture/__init__.py
    - src/hdmi_exfil/display/__init__.py
    - src/hdmi_exfil/file_handling/__init__.py
    - src/hdmi_exfil/cli/__init__.py
  modified: []

key-decisions:
  - "Build backend: setuptools.build_meta (standard, compatible with pip editable installs)"
  - "Constants in decimal JSON for cross-language compatibility (0xDA7A = 55930, 0xF0C0 = 61632)"
  - "Frame types defined in config.py not constants.json (protocol-specific, not encoding parameters)"

patterns-established:
  - "src-layout: all package code under src/hdmi_exfil/"
  - "importlib.resources for loading package data files"
  - "constants.json as single source of truth, config.py computes derived values"

duration: 2min
completed: 2026-02-16
---

# Phase 3 Plan 1: Package Scaffold Summary

**Installable hdmi_exfil package with src-layout, constants.json single source of truth, and config.py exposing all encoding parameters via importlib.resources**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-16T13:46:40Z
- **Completed:** 2026-02-16T13:48:56Z
- **Tasks:** 1
- **Files created:** 9

## Accomplishments
- pyproject.toml with setuptools build, editable install, dev deps, pytest config, CLI entry point stubs
- src/hdmi_exfil/ package with subdirectories for all future modules (protocols, capture, display, file_handling, cli)
- constants.json containing width, height, block_size, seq_magic, fountain_magic, threshold
- config.py loading constants.json via importlib.resources, computing all derived values (COLS, ROWS, BLOCKS_PER_FRAME, BITS_PER_FRAME, BYTES_PER_FRAME, HEADER_SIZE) matching common.py exactly
- All 58 existing tests pass unchanged -- zero impact on existing code

## Task Commits

Each task was committed atomically:

1. **Task 1: Create package scaffold and constants.json** - `3b018ad` (feat)

**Plan metadata:** (pending)

## Files Created/Modified
- `pyproject.toml` - Build config, dependencies, entry points, pytest config
- `src/hdmi_exfil/__init__.py` - Package marker with __version__ = "0.1.0"
- `src/hdmi_exfil/constants.json` - Single source of truth for encoding parameters
- `src/hdmi_exfil/config.py` - Constants loader with derived values
- `src/hdmi_exfil/protocols/__init__.py` - Empty init for future protocol modules
- `src/hdmi_exfil/capture/__init__.py` - Empty init for future capture modules
- `src/hdmi_exfil/display/__init__.py` - Empty init for future display modules
- `src/hdmi_exfil/file_handling/__init__.py` - Empty init for future file handling modules
- `src/hdmi_exfil/cli/__init__.py` - Empty init for future CLI modules

## Decisions Made
- Used `setuptools.build_meta` as build backend (standard, reliable editable installs)
- Stored magic numbers as decimal in JSON (55930, 61632) for cross-language compatibility; hex representation only in Python config.py
- Frame types (IDLE, START, DATA, END) kept in config.py not constants.json since they are protocol-specific constants, not encoding parameters
- pytest.ini left untouched -- pyproject.toml has pytest config but pytest.ini takes precedence for existing tests; will be removed in 03-07

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Initial pyproject.toml used wrong build-backend string (`setuptools.backends._legacy:_Backend`); corrected to `setuptools.build_meta` before successful install. No impact on final result.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Package is installable and importable from anywhere via `from hdmi_exfil.config import *`
- All subsequent 03-XX plans can import from hdmi_exfil package
- Directory structure ready for module migrations (03-02 through 03-06)
- No blockers or concerns

---
*Phase: 03-architecture-refactor*
*Completed: 2026-02-16*
