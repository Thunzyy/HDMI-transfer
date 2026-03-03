---
phase: 08-interactive-sender-console
plan: 01
subsystem: cli
tags: [refactor, inquirerpy, sender, cli, extract-function]

# Dependency graph
requires:
  - phase: 07-monorepo-restructure
    provides: "sender.cli.send module at new path with pyproject.toml extras"
provides:
  - "run_send() standalone function callable without argparse"
  - "InquirerPy dependency in sender extras"
  - "hdmi-sender entry point stub in pyproject.toml"
affects: [08-02-interactive-console-ui]

# Tech tracking
tech-stack:
  added: [InquirerPy >= 0.3.4, pfzy >= 0.3.4]
  patterns: [thin-cli-wrapper, extract-core-function]

key-files:
  created: []
  modified:
    - src/hdmi_exfil/sender/cli/send.py
    - pyproject.toml

key-decisions:
  - "run_send() uses explicit parameters matching argparse defaults for clean API"
  - "hdmi-sender entry point declared early pointing to console:main (module created in Plan 02)"

patterns-established:
  - "Thin CLI wrapper: main() parses args then delegates to run_X() with explicit params"

requirements-completed: [SEND-01, SEND-05]

# Metrics
duration: 2min
completed: 2026-03-03
---

# Phase 8 Plan 1: CLI Send Extraction Summary

**Extracted run_send() from monolithic main() for argparse-free invocation, added InquirerPy to sender extras**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-03T12:50:01Z
- **Completed:** 2026-03-03T12:52:35Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Extracted all post-argparse logic from main() into run_send() with 8 explicit parameters
- main() is now a thin 6-line wrapper: parse args -> call run_send()
- Added InquirerPy >= 0.3.4 to sender extras and hdmi-sender entry point to pyproject.toml
- All 34 existing tests pass (zero regressions from refactor)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract run_send() from main()** - `e6be2b1` (refactor)
2. **Task 2: Add InquirerPy to sender extras** - `fb9df64` (chore)

## Files Created/Modified
- `src/hdmi_exfil/sender/cli/send.py` - Refactored: run_send() extracted with explicit params, main() thin wrapper
- `pyproject.toml` - Added InquirerPy to sender extras, hdmi-sender entry point

## Decisions Made
- run_send() signature uses explicit parameters with sensible defaults matching argparse defaults (mode="sequential", renderer_type="pygame", screen=0, redundancy=1)
- hdmi-sender entry point declared early (pointing to sender.cli.console:main) even though the module is created in Plan 02

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- run_send() is importable and callable with explicit parameters -- ready for interactive console (Plan 02)
- InquirerPy is installed and importable -- ready for menu UI construction
- hdmi-sender entry point is declared -- console module just needs to be created

## Self-Check: PASSED

All files exist, all commits verified, all functional checks pass.

---
*Phase: 08-interactive-sender-console*
*Completed: 2026-03-03*
