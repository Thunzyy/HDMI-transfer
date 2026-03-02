---
phase: 07-monorepo-restructure
plan: 02
subsystem: structure
tags: [monorepo, subpackages, import-shims, pyproject, src-layout, backward-compat]

# Dependency graph
requires:
  - phase: 07-monorepo-restructure
    provides: "cv2-free protocols and sampler (07-01)"
provides:
  - "src/hdmi_exfil/{core,sender,receiver}/ subpackage structure"
  - "26 backward-compatible shim modules at old hdmi_exfil.* paths"
  - "pyproject.toml with auto-discovery and hdmi_exfil.core package-data"
  - "Zero test regressions -- all 306 tests pass unchanged"
affects: [07-03, pyproject-extras, sender-console, receiver-console]

# Tech tracking
tech-stack:
  added: []
  patterns: ["backward-compatible shim modules via wildcard re-export", "setuptools auto-discovery with find", "three-layer subpackage split: core/sender/receiver"]

key-files:
  created:
    - "src/hdmi_exfil/__init__.py"
    - "src/hdmi_exfil/core/__init__.py"
    - "src/hdmi_exfil/core/config.py"
    - "src/hdmi_exfil/core/prng.py"
    - "src/hdmi_exfil/core/constants.json"
    - "src/hdmi_exfil/core/protocols/__init__.py"
    - "src/hdmi_exfil/core/protocols/base.py"
    - "src/hdmi_exfil/core/protocols/degree.py"
    - "src/hdmi_exfil/core/protocols/fountain.py"
    - "src/hdmi_exfil/core/protocols/sequential.py"
    - "src/hdmi_exfil/core/protocols/xor_ops.py"
    - "src/hdmi_exfil/core/file_handling/metadata.py"
    - "src/hdmi_exfil/core/file_handling/reader.py"
    - "src/hdmi_exfil/core/file_handling/writer.py"
    - "src/hdmi_exfil/core/capture/sampler.py"
    - "src/hdmi_exfil/core/capture/threaded.py"
    - "src/hdmi_exfil/core/cli/benchmark.py"
    - "src/hdmi_exfil/core/cli/progress.py"
    - "src/hdmi_exfil/sender/__init__.py"
    - "src/hdmi_exfil/sender/display/monitors.py"
    - "src/hdmi_exfil/sender/display/renderer.py"
    - "src/hdmi_exfil/sender/display/test_patterns.py"
    - "src/hdmi_exfil/sender/cli/send.py"
    - "src/hdmi_exfil/receiver/__init__.py"
    - "src/hdmi_exfil/receiver/capture/source.py"
    - "src/hdmi_exfil/receiver/cli/receive.py"
    - "src/hdmi_exfil/receiver/cli/calibrate.py"
  modified:
    - "pyproject.toml"

key-decisions:
  - "Used wildcard re-export shims (from X import *) at old paths instead of updating test imports -- safer and zero-disruption"
  - "Used setuptools auto-discovery (find) instead of manual package list -- avoids missing subpackages as structure grows"
  - "Updated importlib.resources path from files('hdmi_exfil') to files('hdmi_exfil.core') for constants.json"

patterns-established:
  - "Shim module pattern: one-line 'from hdmi_exfil.core.X import *' at old import path"
  - "Core imports use hdmi_exfil.core.* canonical paths; sender/receiver import from core"
  - "No circular dependencies: core never imports from sender/receiver"

requirements-completed: [STRUCT-01]

# Metrics
duration: 21min
completed: 2026-03-02
---

# Phase 7 Plan 2: Monorepo Directory Restructure Summary

**Reorganized flat src/ into src/hdmi_exfil/{core,sender,receiver}/ subpackages with 26 backward-compatible shim modules preserving all old import paths**

## Performance

- **Duration:** 21 min
- **Started:** 2026-03-02T20:33:28Z
- **Completed:** 2026-03-02T20:54:28Z
- **Tasks:** 2
- **Files modified:** 60+ (34 created in new structure, 26 shims, 3 old files deleted, pyproject.toml updated)

## Accomplishments
- Created complete src/hdmi_exfil/{core,sender,receiver}/ directory tree with 12 subpackages
- Moved all 26 source files to canonical locations with updated internal imports
- Created 26 backward-compatible shim modules at old hdmi_exfil.* paths ensuring zero test disruption
- Updated pyproject.toml to use setuptools auto-discovery and correct package-data path
- All 306 tests pass with zero import changes in test files (3 pre-existing failures unchanged)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create subpackage directories and move files** - `3ff7b4f` (feat)
2. **Task 2: Create backward-compatible shim modules** - `22fb607` (feat)

## Files Created/Modified

### Core subpackage (src/hdmi_exfil/core/)
- `core/__init__.py` - Core subpackage root
- `core/config.py` - Configuration with updated importlib.resources path
- `core/prng.py` - PRNG with updated imports to core.protocols.degree
- `core/constants.json` - Encoding constants data file
- `core/protocols/__init__.py` - Protocol registry with core.protocols.* imports
- `core/protocols/base.py` - Protocol ABC (unchanged)
- `core/protocols/degree.py` - RSD distribution (unchanged)
- `core/protocols/fountain.py` - Fountain protocol with core.* imports
- `core/protocols/sequential.py` - Sequential protocol with core.* imports
- `core/protocols/xor_ops.py` - Numba XOR operations (unchanged)
- `core/file_handling/{metadata,reader,writer}.py` - File handling (pure stdlib, unchanged)
- `core/capture/{sampler,threaded}.py` - Capture utilities (unchanged)
- `core/cli/{benchmark,progress}.py` - CLI utilities with core.* imports

### Sender subpackage (src/hdmi_exfil/sender/)
- `sender/display/{monitors,renderer,test_patterns}.py` - Display modules with core.* imports
- `sender/cli/send.py` - Send CLI with core.* and sender.* imports

### Receiver subpackage (src/hdmi_exfil/receiver/)
- `receiver/capture/source.py` - VideoCapture wrapper (cv2, unchanged)
- `receiver/cli/{receive,calibrate}.py` - Receive CLI with core.* and receiver.* imports

### Shim modules (26 files at old import paths)
- `config.py`, `prng.py` - Top-level shims
- `protocols/{__init__,base,degree,fountain,sequential,xor_ops}.py` - Protocol shims
- `capture/{__init__,sampler,threaded,source}.py` - Capture shims
- `display/{__init__,monitors,renderer,test_patterns}.py` - Display shims
- `file_handling/{__init__,metadata,reader,writer}.py` - File handling shims
- `cli/{__init__,send,receive,calibrate,benchmark,progress}.py` - CLI shims

### Configuration
- `pyproject.toml` - Updated to use auto-discovery and hdmi_exfil.core package-data

## Decisions Made
- Used wildcard re-export shims (`from hdmi_exfil.core.X import *`) at old paths instead of updating test imports -- safer, zero-disruption approach
- Used setuptools auto-discovery (`[tool.setuptools.packages.find]`) instead of manual package list -- avoids missing subpackages as structure grows
- Updated `importlib.resources.files("hdmi_exfil")` to `files("hdmi_exfil.core")` for constants.json since it moved to core/

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- STRUCT-01 complete: code organized into core/, sender/, receiver/ subpackages
- Ready for 07-03 (pyproject.toml extras split for sender/receiver optional dependencies)
- Pre-existing failures remain: test_xor_ops.py::test_fountain_decoder_with_numba, test_rsd_cross_language.py (2 tests) -- all unrelated to restructure

## Self-Check: PASSED

All 15 key files verified present on disk. Both commit hashes (3ff7b4f, 22fb607) verified in git history.

---
*Phase: 07-monorepo-restructure*
*Completed: 2026-03-02*
