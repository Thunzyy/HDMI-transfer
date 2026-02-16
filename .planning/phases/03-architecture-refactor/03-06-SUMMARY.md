---
phase: 03-architecture-refactor
plan: 06
subsystem: cli
tags: [argparse, cli, build-system, constants-injection, web]

# Dependency graph
requires:
  - phase: 03-03
    provides: SequentialProtocol with encode/decode and TransferState enum
  - phase: 03-04
    provides: FountainProtocol, FountainDecoder, and get_protocol registry
  - phase: 03-05
    provides: CaptureSource, FrameRenderer, get_monitors, read_input, write_output, sample_frame
provides:
  - "hdmi-send CLI command wiring all package modules for transmission"
  - "hdmi-recv CLI command wiring all package modules for reception"
  - "web/build_sender.py generating sender.html from template + constants.json"
  - "web/sender.template.html with {{CONST_*}} placeholders"
affects: [04-performance, 06-ux]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CLI as thin orchestrator (no encoding logic, just wiring)"
    - "Constants injection via template placeholders for cross-language sync"

key-files:
  created:
    - src/hdmi_exfil/cli/send.py
    - src/hdmi_exfil/cli/receive.py
    - web/sender.template.html
    - web/build_sender.py
  modified: []

key-decisions:
  - "CLI modules import only from hdmi_exfil.* -- never from old flat modules"
  - "Fountain magic rendered as hex literal (0xF0C0) in JS for readability"
  - "Build script uses importlib.resources for package-relative constants.json access"
  - "Auto-detect mode in receiver tries sequential first, then fountain"

patterns-established:
  - "CLI thin-orchestrator: send.py and receive.py contain zero encoding/decoding logic"
  - "Template-based web build: single source of truth for constants across Python and JS"

# Metrics
duration: 6min
completed: 2026-02-16
---

# Phase 3 Plan 6: CLI & Web Build Summary

**hdmi-send/hdmi-recv CLI entry points wiring all package modules, plus web build system injecting constants.json into sender.template.html**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-16T14:10:46Z
- **Completed:** 2026-02-16T14:16:17Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments
- `hdmi-send` CLI with argparse (input_path, --mode, --fps, --redundancy, --screen) driving both sequential and fountain send loops
- `hdmi-recv` CLI with argparse (source, --output, --mode) supporting auto-detect, sequential, and fountain receive modes
- `web/build_sender.py` reads constants.json from installed package and generates sender.html from template
- Generated sender.html is byte-identical to the original (constants synced from single source)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CLI entry points** - `93f3e31` (feat)
2. **Task 2: Create web sender build system** - `45cd5b8` (feat)

## Files Created/Modified
- `src/hdmi_exfil/cli/send.py` - hdmi-send entry point: file reading, protocol dispatch, display loop with pause/resume UX
- `src/hdmi_exfil/cli/receive.py` - hdmi-recv entry point: capture source, protocol auto-detection, sequential/fountain receive loops
- `web/sender.template.html` - HTML template with {{CONST_WIDTH}}, {{CONST_HEIGHT}}, {{CONST_BLOCK_SIZE}}, {{CONST_FOUNTAIN_MAGIC}} placeholders
- `web/build_sender.py` - Build script reading constants.json via importlib.resources, replacing placeholders, writing sender.html

## Decisions Made
- CLI modules are thin orchestrators with zero encoding/decoding logic -- all work delegated to protocol classes
- Fountain magic converted to hex literal (0xF0C0) in JS output for readability; stored as decimal (61632) in JSON
- Build script uses `importlib.resources.files("hdmi_exfil")` for reliable package-relative constants.json access
- Auto-detect mode tries sequential decode first (checks magic 0xDA7A), falls back to fountain (0xF0C0)
- Pause/resume UX replicated from original sender.py (ESC to pause, 'r' to resume, 'q' to quit)

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None -- no external service configuration required.

## Next Phase Readiness
- All 6 of 7 architecture refactor plans complete
- CLI entry points ready; `hdmi-send --help` and `hdmi-recv --help` work
- Web build system ensures constants stay synced when parameters change
- Final plan (03-07) can wire integration tests or finalize migration

---
*Phase: 03-architecture-refactor*
*Completed: 2026-02-16*
