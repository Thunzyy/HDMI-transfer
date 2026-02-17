---
phase: 05-fountain-code-optimization
plan: 02
subsystem: protocols
tags: [fountain, lt-codes, gaussian-elimination, gf2, decoder, peeling, hybrid-bp-ge]

# Dependency graph
requires:
  - phase: 05-fountain-code-optimization
    provides: "Plan 05-01: degree.py RSD module, FountainDecoder with RSD-based add_droplet"
  - phase: 04-performance-optimization
    provides: "Numba xor_into, numpy-based chunk storage"
provides:
  - "gaussian_elimination_fallback() method on FountainDecoder"
  - "try_gaussian_elimination() auto-trigger from add_droplet"
  - "Hybrid BP+GE decoder recovers chunks when peeling stalls"
  - "12 unit tests for GE fallback in test_fountain_ge.py"
affects:
  - "05-03: JS sender unaffected (GE is receiver-only)"
  - "05-04: Overhead benchmarks should measure BP+GE combined recovery"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GF(2) Gaussian elimination via numpy uint8 XOR row operations"
    - "Full RREF in one pass (forward elimination eliminates ALL rows, not just below pivot)"
    - "Auto-trigger GE after each add_droplet when n_unresolved >= n_unknown"

key-files:
  created:
    - "tests/test_fountain_ge.py"
  modified:
    - "src/hdmi_exfil/protocols/fountain.py"

key-decisions:
  - "GE uses numpy dense uint8 matrix (not sparse) -- simple and fast for K < 1000"
  - "Full RREF in one pass (eliminate all rows, not just below pivot) -- avoids separate back-substitution step"
  - "Auto-trigger after every add_droplet with lightweight n_unresolved >= n_unknown guard"
  - "GE copies unresolved droplet data to avoid mutating decoder state on failure"
  - "Test equations must be linearly independent in GF(2) ({2,3},{3,4},{2,4} is rank 2, not 3)"

patterns-established:
  - "Hybrid BP+GE: peeling first (O(n) per symbol), GE only when stalled (O(n^2*m) one-shot)"
  - "resolve_chunk() as shared entry point: both BP and GE feed recovered chunks through same propagation path"

# Metrics
duration: 9min
completed: 2026-02-17
---

# Phase 5 Plan 2: Gaussian Elimination Fallback Decoder Summary

**GF(2) Gaussian elimination fallback on FountainDecoder with auto-trigger from add_droplet, recovering chunks when belief-propagation peeling stalls for small K**

## Performance

- **Duration:** 9 min
- **Started:** 2026-02-17T00:04:54Z
- **Completed:** 2026-02-17T00:13:35Z
- **Tasks:** 2 (TDD: RED, GREEN) -- no refactor needed
- **Files modified:** 2

## Accomplishments
- Implemented `gaussian_elimination_fallback()` on FountainDecoder: builds GF(2) binary matrix from unresolved droplets, row-reduces to RREF, back-substitutes to recover unknown chunks
- Implemented `try_gaussian_elimination()` lightweight trigger called from `add_droplet()` after BP processing
- 12 new GE-specific tests pass, all 60 existing tests pass (fountain, RSD, PRNG, 3bpp)
- GE correctly handles: full-rank systems, underdetermined systems, already-complete decoder, empty unresolved set

## Task Commits

Each task was committed atomically:

1. **RED: Failing GE tests** - `6b3aadd` (test)
2. **GREEN: Implement GE + fix test equations** - `bb3f985` (feat)

_TDD cycle: RED (5 failing tests) -> GREEN (12 passing) -- no refactor commit needed_

## Files Created/Modified
- `tests/test_fountain_ge.py` - 12 tests: BP stall recovery, K=10 partial, underdetermined, auto-trigger, round-trip K=3/5/10/20, existing compat
- `src/hdmi_exfil/protocols/fountain.py` - Added `gaussian_elimination_fallback()`, `try_gaussian_elimination()`, auto-trigger in `add_droplet()`

## Decisions Made
- **Dense numpy matrix for GE:** uint8 matrix with XOR row operations -- simple, fast, correct for GF(2). Sparse/bitarray unnecessary for K < 1000.
- **Full RREF in one pass:** The elimination loop eliminates ALL other rows (not just below pivot), producing reduced row echelon form directly without a separate back-substitution phase.
- **Auto-trigger guard:** `try_gaussian_elimination()` counts unresolved droplets vs unknown chunks before invoking the full solver. This is O(n) vs the O(n^2*m) GE, so the per-droplet overhead is negligible.
- **Copy unresolved data:** GE copies both indices and data arrays from droplets to avoid mutating decoder state if GE fails (underdetermined system).
- **resolve_chunk() as shared entry point:** GE-recovered chunks are fed through the same `resolve_chunk()` method as BP, triggering further peeling propagation automatically.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test equations were linearly dependent in GF(2)**
- **Found during:** Task 2 (GREEN -- initial test run)
- **Issue:** The manually constructed test equations `{2,3}, {3,4}, {2,4}` form a rank-2 system in GF(2) (eq0 XOR eq1 XOR eq2 = 0), not rank-3 as intended. GE correctly identified the system as unsolvable and returned False.
- **Fix:** Changed to `{2,3}, {3,4}, {2,3,4}` which is rank-3 (full rank). Similarly for K=10 test: `{7,8}, {8,9}, {7,8,9}`.
- **Files modified:** tests/test_fountain_ge.py
- **Verification:** All 12 tests pass
- **Committed in:** bb3f985

---

**Total deviations:** 1 auto-fixed (1 bug in test data)
**Impact on plan:** Test data correction only. GE implementation was correct from the start. No scope creep.

## Issues Encountered
None beyond the test data correction documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- GE fallback fully operational for all K values tested (K=1,3,5,10,20)
- Existing round-trip tests and 3bpp tests unaffected
- Ready for plan 05-03 (JS sender RSD sync) and 05-04 (overhead benchmarks)
- Overhead benchmarks should now measure combined BP+GE recovery rate

---
*Phase: 05-fountain-code-optimization*
*Completed: 2026-02-17*
