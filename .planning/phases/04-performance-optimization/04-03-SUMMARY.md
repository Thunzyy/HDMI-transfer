---
phase: 04-performance-optimization
plan: 03
subsystem: display
tags: [pygame-ce, sdl2, vsync, rendering, opencv-headless, numba]

# Dependency graph
requires:
  - phase: 03-architecture-refactor
    provides: "FrameRenderer class in src/hdmi_exfil/display/renderer.py"
provides:
  - "PygameRenderer class with SDL2 vsync-locked fullscreen rendering"
  - "pygame-ce and opencv-python-headless dependencies in pyproject.toml"
  - "numba dependency pre-installed for plan 04-02"
affects: [04-05-cli-wiring, 06-ux-polish]

# Tech tracking
tech-stack:
  added: [pygame-ce >= 2.5.0, opencv-python-headless >= 4.0, numba >= 0.60.0]
  patterns: [lazy-import-for-optional-backend, dual-renderer-coexistence]

key-files:
  modified:
    - src/hdmi_exfil/display/renderer.py
    - pyproject.toml
  created:
    - tests/test_pygame_renderer.py

key-decisions:
  - "pygame lazy import inside __init__ so module importable in headless/CI"
  - "opencv-python replaced with opencv-python-headless to avoid SDL2 conflicts"
  - "numba added now to avoid double-reinstall when plan 04-02 executes"
  - "PygameRenderer returns 255 for no-key (matching FrameRenderer convention)"

patterns-established:
  - "Dual renderer pattern: FrameRenderer (cv2) and PygameRenderer (pygame-ce) coexist"
  - "Lazy import for heavy optional deps (pygame inside __init__, not module level)"

# Metrics
duration: 3min
completed: 2026-02-16
---

# Phase 4 Plan 3: PygameRenderer SDL2 Display Summary

**PygameRenderer with SDL2 vsync-locked fullscreen rendering via pygame-ce, replacing cv2.imshow ~80fps ceiling**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-16T22:38:56Z
- **Completed:** 2026-02-16T22:42:16Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added PygameRenderer class with SDL2 vsync-locked fullscreen rendering alongside existing FrameRenderer
- Updated dependencies: pygame-ce >= 2.5.0, opencv-python-headless >= 4.0, numba >= 0.60.0
- PygameRenderer handles BGR->RGB conversion and (H,W,3)->(W,H,3) transpose internally for drop-in compatibility
- 7 unit tests verify import, interface parity, conversion pipeline, and signature compatibility (all headless-safe)

## Task Commits

Each task was committed atomically:

1. **Task 1: Update dependencies and add PygameRenderer** - `708b0d5` (feat)
2. **Task 2: Add PygameRenderer unit tests** - `af1dc07` (test)

## Files Created/Modified
- `src/hdmi_exfil/display/renderer.py` - Added PygameRenderer class (SDL2 vsync-locked fullscreen rendering)
- `pyproject.toml` - Updated deps: pygame-ce, opencv-python-headless, numba
- `tests/test_pygame_renderer.py` - 7 headless-safe tests for PygameRenderer

## Decisions Made
- pygame imported lazily inside `PygameRenderer.__init__` so the module can be imported without pygame installed (headless/CI)
- Replaced `opencv-python` with `opencv-python-headless` to prevent SDL2 namespace conflicts with pygame-ce
- Pre-installed `numba >= 0.60.0` alongside pygame-ce to avoid a second `pip install -e .` during plan 04-02
- PygameRenderer.show() returns 255 for no-key-pressed, matching FrameRenderer convention for drop-in replacement
- Pre-allocated pygame.Surface avoids per-frame allocation overhead

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- PygameRenderer ready for integration into CLI send pipeline (plan 04-05)
- FrameRenderer remains available as fallback for environments without pygame-ce
- Plans 04-02 (numba JIT) and 04-05 (CLI wiring) are unblocked

---
*Phase: 04-performance-optimization*
*Completed: 2026-02-16*
