---
phase: 08-interactive-sender-console
plan: 02
subsystem: cli
tags: [inquirerpy, sender, interactive-menu, arrow-key, console, dispatch]

# Dependency graph
requires:
  - phase: 08-interactive-sender-console
    plan: 01
    provides: "run_send() standalone function, InquirerPy dependency, hdmi-sender entry point"
provides:
  - "Interactive sender console with arrow-key main menu"
  - "Parameter collection via InquirerPy (filepath, profile, mode, monitor)"
  - "Action dispatch to run_send(), _cmd_send(), run_benchmark(), get_monitors()"
  - "Backward-compatible shim at cli/sender_console.py"
  - "Unit tests for console dispatch and parameter mapping"
affects: [09-interactive-receiver-console]

# Tech tracking
tech-stack:
  added: []
  patterns: [interactive-menu-dispatch, parameter-collection-then-delegate, ctrl-c-nested-handler]

key-files:
  created:
    - src/hdmi_exfil/sender/cli/console.py
    - src/hdmi_exfil/cli/sender_console.py
    - tests/test_sender_console.py
  modified: []

key-decisions:
  - "Console uses _DISPATCH dict mapping menu strings to handler functions for clean extensibility"
  - "Ctrl-C uses nested try/except: inner catches during action (returns to menu), outer catches during prompt (exits cleanly)"
  - "Single-monitor case skips monitor selection prompt for UX simplicity"

patterns-established:
  - "Interactive menu dispatch: _DISPATCH dict maps menu labels to handler functions"
  - "Parameter collection: InquirerPy prompts collect all params, then single delegate call"
  - "Nested Ctrl-C: outer handler for clean exit, inner handler for action cancellation"

requirements-completed: [SEND-01, SEND-02, SEND-03, SEND-04, SEND-05, SEND-06, SEND-07, SEND-08]

# Metrics
duration: 4min
completed: 2026-03-03
---

# Phase 8 Plan 2: Interactive Sender Console Summary

**Arrow-key interactive console (hdmi-sender) with InquirerPy menu, filepath tab-completion, profile/mode/monitor selection, and clean Ctrl-C dispatch to run_send/calibrate/benchmark**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-03T12:55:46Z
- **Completed:** 2026-03-03T13:00:01Z
- **Tasks:** 2
- **Files created:** 3

## Accomplishments
- Created interactive sender console with 6-action main menu (Send Python, Send Browser, Calibrate, Detect, Benchmark, Quit)
- Parameter collection via InquirerPy: filepath with tab-completion, profile/mode/monitor arrow-key selection
- Console delegates to existing functions without duplicating any encoding/display/protocol logic
- Clean Ctrl-C handling: exits at prompt, returns to menu during action
- 7 unit tests covering dispatch, parameter flow, Ctrl-C, Quit, and action delegation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create interactive sender console module** - `a90468d` (feat)
2. **Task 2: Add unit tests for sender console** - `90edcd9` (test)

## Files Created/Modified
- `src/hdmi_exfil/sender/cli/console.py` - Interactive console with main menu, 5 action handlers, dispatch loop, Ctrl-C handling (186 lines)
- `src/hdmi_exfil/cli/sender_console.py` - Backward-compatible import shim
- `tests/test_sender_console.py` - 7 unit tests for dispatch, delegation, and clean exit behavior

## Decisions Made
- Console uses _DISPATCH dict mapping menu strings to handler functions -- clean, extensible, testable
- Ctrl-C uses nested try/except: inner catches during action (returns to menu), outer catches during prompt (exits cleanly)
- Single-monitor case auto-selects screen 0 instead of showing a 1-item selection prompt
- Browser sender action searches for sender.html via relative path and cwd, with graceful fallback message

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_main_dispatches_action mock target**
- **Found during:** Task 2 (unit tests)
- **Issue:** Patching _action_detect on the module doesn't affect the _DISPATCH dict (populated at import time with real function references)
- **Fix:** Used patch.dict(_DISPATCH, ...) instead of patching the function directly
- **Files modified:** tests/test_sender_console.py
- **Verification:** All 7 tests pass
- **Committed in:** 90edcd9 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix in test)
**Impact on plan:** Test mock strategy adjusted for correctness. No scope creep.

## Issues Encountered
- Pre-existing test failures remain (test_xor_ops.py::test_fountain_decoder_with_numba and test_rsd_cross_language.py) -- not introduced by this plan

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 8 complete -- interactive sender console fully operational
- hdmi-sender entry point resolves to sender.cli.console:main
- Pattern established for Phase 9 (interactive receiver console): same menu dispatch + parameter collection approach
- InquirerPy already installed as sender dependency, ready for receiver extras in Phase 9

## Self-Check: PASSED

All files exist, all commits verified, line count minimums met (console.py: 218 >= 80, tests: 179 >= 40).

---
*Phase: 08-interactive-sender-console*
*Completed: 2026-03-03*
