---
phase: 07-monorepo-restructure
plan: 01
subsystem: protocols
tags: [numpy, cv2-removal, np-repeat, nearest-neighbor, monorepo]

# Dependency graph
requires:
  - phase: 05-fountain-code-optimization
    provides: "Fountain protocol with 3bpp encoding and GE decoder"
provides:
  - "cv2-free SequentialProtocol.encode_frame using np.repeat"
  - "cv2-free FountainProtocol.encode_frame using np.repeat"
  - "cv2-free sample_frame using np.linspace + fancy indexing"
  - "AST-based test suite verifying zero cv2 imports"
affects: [07-02, 07-03, monorepo-split]

# Tech tracking
tech-stack:
  added: []
  patterns: ["np.repeat for nearest-neighbor block upscale", "np.linspace + fancy indexing for nearest-neighbor resize"]

key-files:
  created:
    - "tests/test_no_cv2_in_protocols.py"
  modified:
    - "src/protocols/sequential.py"
    - "src/protocols/fountain.py"
    - "src/capture/sampler.py"

key-decisions:
  - "Used np.repeat (axis=0 then axis=1) + trim for block upscale -- proven pattern from test_patterns.py"
  - "Used np.linspace + fancy indexing for dimension-mismatch resize in sampler -- handles both upscale and downscale"

patterns-established:
  - "np.repeat upscale: np.repeat(np.repeat(grid, bs, axis=0), bs, axis=1) + safety trim"
  - "numpy nearest-neighbor resize: np.linspace(0, src-1, dst, dtype=int) + fancy indexing"

requirements-completed: [STRUCT-06]

# Metrics
duration: 5min
completed: 2026-03-02
---

# Phase 7 Plan 1: cv2 Removal from Protocol Encoding Summary

**Replaced all cv2.resize calls in protocol encoding and frame sampling with pure numpy equivalents (np.repeat upscale, np.linspace resize) -- unblocking monorepo core/extras split**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-02T20:23:21Z
- **Completed:** 2026-03-02T20:28:36Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Removed cv2 dependency from sequential.py, fountain.py, and sampler.py (3 files, zero cv2 imports)
- All 170 tests pass with zero regressions (2 pre-existing failures unrelated to changes)
- STRUCT-06 blocker resolved -- protocols and sampler can now live in core/ without OpenCV

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace cv2.resize with np.repeat in protocol encoding** - `05b6ecd` (test: RED) + `a541704` (feat: GREEN)
2. **Task 2: Replace cv2.resize with numpy indexing in capture/sampler.py** - `7d427bb` (feat: GREEN, RED tests shared in commit 05b6ecd)

_Note: TDD RED tests for both tasks were written in a single test file and committed together._

## Files Created/Modified
- `tests/test_no_cv2_in_protocols.py` - AST-based tests verifying no cv2 imports + shape/uniformity tests
- `src/protocols/sequential.py` - Removed `import cv2`, replaced cv2.resize with np.repeat in encode_frame
- `src/protocols/fountain.py` - Removed lazy `import cv2`, replaced cv2.resize with np.repeat in encode_frame
- `src/capture/sampler.py` - Removed lazy `import cv2`, replaced cv2.resize with np.linspace + fancy indexing

## Decisions Made
- Used np.repeat (axis=0 then axis=1) + safety trim for block upscale -- matches proven pattern in test_patterns.py line 53
- Used np.linspace + fancy indexing for sampler resize -- handles both upscale/downscale and doesn't require block_size to be an integer divisor

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- STRUCT-06 resolved: protocols and sampler are now cv2-free
- Ready for 07-02 (monorepo directory restructure) -- core/ package can now include protocols and sampler without OpenCV dependency
- Pre-existing failures remain: test_xor_ops.py::test_fountain_decoder_with_numba and test_rsd_cross_language.py (both unrelated to this plan)

## Self-Check: PASSED

All 5 files verified present on disk. All 3 commits verified in git history.

---
*Phase: 07-monorepo-restructure*
*Completed: 2026-03-02*
