---
phase: 07-monorepo-restructure
plan: 03
subsystem: packaging
tags: [pyproject, pip-extras, optional-dependencies, sender-receiver-split, setuptools]

# Dependency graph
requires:
  - phase: 07-monorepo-restructure
    provides: "core/sender/receiver subpackage structure with shims (07-02)"
provides:
  - "pyproject.toml with sender/receiver/all/dev pip extras"
  - "Core dependencies reduced to numpy + numba only"
  - "Selective install: pip install hdmi-exfil[sender] or hdmi-exfil[receiver]"
  - "All 4 CLI entry points verified working"
  - "Full test suite passing (pre-existing failures only)"
affects: [08-sender-console, 09-receiver-console, packaging, distribution]

# Tech tracking
tech-stack:
  added: []
  patterns: ["pip extras for optional dependency groups", "self-referential extras (all = [sender] + [receiver])"]

key-files:
  created: []
  modified:
    - "pyproject.toml"

key-decisions:
  - "Core dependencies limited to numpy + numba; pygame-ce/screeninfo/opencv-python moved to extras"
  - "Self-referential extras syntax: hdmi-exfil[all] depends on hdmi-exfil[sender] + hdmi-exfil[receiver]"
  - "Dev extra includes all + test tools, ensuring developers get full environment"

patterns-established:
  - "Extras pattern: [sender] for display/pygame deps, [receiver] for capture/cv2 deps"
  - "Install patterns: pip install hdmi-exfil (core only), pip install hdmi-exfil[sender], pip install hdmi-exfil[all]"

requirements-completed: [STRUCT-02, STRUCT-03, STRUCT-04, STRUCT-05, STRUCT-07]

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 7 Plan 3: Pyproject Extras Split Summary

**pip extras split: sender (pygame-ce, screeninfo), receiver (opencv-python), all, dev -- core dependencies reduced to numpy + numba only**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-02T21:01:07Z
- **Completed:** 2026-03-02T21:04:28Z
- **Tasks:** 2
- **Files modified:** 1 (pyproject.toml)

## Accomplishments
- Moved pygame-ce and screeninfo to [sender] optional extra
- Moved opencv-python to [receiver] optional extra
- Added [all] meta-extra combining sender + receiver, and [dev] meta-extra adding test tools
- Core [project.dependencies] reduced to numpy + numba only
- All 4 CLI entry points (hdmi-send, hdmi-recv, hdmi-calibrate, hdmi-bench) verified working
- Full test suite: 170 passed, 1 pre-existing failure (test_fountain_decoder_with_numba), 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Update pyproject.toml with extras and package auto-discovery** - `8e7cd42` (feat)
2. **Task 2: Verify CLI entry points and full test suite** - verification-only, no commit needed

## Files Created/Modified
- `pyproject.toml` - Added sender/receiver/all/dev optional-dependencies; reduced core deps to numpy + numba

## Decisions Made
- Core dependencies limited to numpy + numba only -- pygame-ce, screeninfo, opencv-python all moved to extras
- Used self-referential extras syntax (hdmi-exfil[all] = hdmi-exfil[sender] + hdmi-exfil[receiver]) for clean composition
- Dev extra includes all + test tools, so `pip install -e ".[dev]"` gives developers the full environment

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 7 (Monorepo Restructure) is now fully complete
- All 3 plans (07-01 cv2 removal, 07-02 directory restructure, 07-03 extras split) delivered
- Requirements STRUCT-01 through STRUCT-07 addressed across the phase
- Ready for Phase 8 (Sender Console) and Phase 9 (Receiver Console)
- Pre-existing test failures remain: test_xor_ops.py::test_fountain_decoder_with_numba, test_rsd_cross_language.py (Windows /dev/stdin issue)

## Self-Check: PASSED

All files verified present on disk. Commit hash 8e7cd42 verified in git history.

---
*Phase: 07-monorepo-restructure*
*Completed: 2026-03-02*
