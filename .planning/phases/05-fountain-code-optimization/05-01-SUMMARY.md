---
phase: 05-fountain-code-optimization
plan: 01
subsystem: protocols
tags: [fountain, lt-codes, rsd, soliton, degree-distribution, prng]

# Dependency graph
requires:
  - phase: 03-architecture-refactor
    provides: "PRNG module (prng.py), FountainDecoder (fountain.py), protocol registry"
  - phase: 04-performance-optimization
    provides: "3bpp encoding, Numba xor_into, ThreadedCapture"
provides:
  - "degree.py: RSD computation (ideal_soliton, robust_soliton_cdf, sample_degree)"
  - "RSD-based choose_indices in prng.py"
  - "RSD-based FountainDecoder.add_droplet in fountain.py"
  - "23 unit tests for RSD math in test_rsd.py"
affects:
  - "05-03: JS sender must be updated to match Python RSD"
  - "05-02: Improved degree distribution reduces overhead"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "functools.lru_cache on CDF computation for repeated calls"
    - "bisect.bisect_left for O(log K) degree sampling from CDF"
    - "Lazy import in prng.py to break circular dependency"

key-files:
  created:
    - "src/hdmi_exfil/protocols/degree.py"
    - "tests/test_rsd.py"
  modified:
    - "src/hdmi_exfil/prng.py"
    - "src/hdmi_exfil/protocols/fountain.py"
    - "tests/test_fountain.py"
    - "tests/test_prng.py"

key-decisions:
  - "Lazy import of degree module in prng.py to avoid circular dependency chain (prng -> degree -> protocols.__init__ -> fountain -> prng)"
  - "bisect.bisect_left for O(log K) CDF sampling instead of linear scan"
  - "CDF forced to exactly 1.0 at last entry to prevent floating-point drift"
  - "test_prng.py JS cross-language vectors deferred to plan 05-03 when JS is updated to RSD"

patterns-established:
  - "Single-source-of-truth: all degree logic in degree.py, imported by both prng.py and fountain.py"
  - "lru_cache(maxsize=64) on CDF computation keyed by (K, c, delta) tuple"

# Metrics
duration: 8min
completed: 2026-02-17
---

# Phase 5 Plan 1: Robust Soliton Distribution Summary

**RSD module (degree.py) with cached CDF computation, O(log K) bisect sampling, wired into both choose_indices and FountainDecoder replacing ad-hoc 10%/50%/40% distribution**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-16T23:53:30Z
- **Completed:** 2026-02-17T00:01:50Z
- **Tasks:** 3 (TDD: RED, GREEN, integration)
- **Files modified:** 6

## Accomplishments
- Created degree.py with ideal_soliton, robust_soliton_cdf (lru_cached), sample_degree (bisect)
- Replaced ad-hoc degree distribution in both prng.py:choose_indices and fountain.py:FountainDecoder.add_droplet
- All 48 tests pass: 23 RSD + 16 fountain round-trip + 9 PRNG determinism
- RSD CDF sums to 1.0 for K=1, 10, 100, 1000, 10000

## Task Commits

Each task was committed atomically:

1. **RED: Failing RSD tests** - `4446bf4` (test)
2. **GREEN: Implement degree.py** - `e7b0371` (feat)
3. **Integration: Wire RSD into prng.py + fountain.py** - `3925d9d` (feat)

_TDD cycle: RED (23 failing tests) -> GREEN (23 passing) -> Integration (48 passing)_

## Files Created/Modified
- `src/hdmi_exfil/protocols/degree.py` - RSD math: ideal_soliton, robust_soliton_cdf, sample_degree
- `tests/test_rsd.py` - 23 unit tests for RSD (CDF monotonicity, sum-to-one, caching, determinism, K=1 edge case)
- `src/hdmi_exfil/prng.py` - choose_indices now uses RSD via lazy import
- `src/hdmi_exfil/protocols/fountain.py` - FountainDecoder.add_droplet now uses RSD
- `tests/test_fountain.py` - _compute_degree helper updated to use RSD
- `tests/test_prng.py` - JS cross-language vectors replaced with determinism tests (JS update deferred to 05-03)

## Decisions Made
- **Lazy import in prng.py:** Circular dependency chain (prng -> degree -> protocols.__init__ -> fountain -> prng) broken by importing degree inside choose_indices function rather than at module level
- **bisect.bisect_left for CDF sampling:** O(log K) lookup instead of linear scan; important for large K values
- **CDF[-1] forced to 1.0:** Prevents floating-point drift from causing sample_degree to return out-of-range values
- **JS cross-language test deferred:** test_prng.py's choose_indices-match-JS vectors used the old ad-hoc distribution; replaced with determinism/range tests pending JS update in plan 05-03

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Circular import between prng.py and protocols/degree.py**
- **Found during:** Task 2 (Integration)
- **Issue:** Top-level import in prng.py triggered circular import: prng -> protocols.degree -> protocols.__init__ -> fountain -> prng
- **Fix:** Changed to lazy import inside choose_indices() function body
- **Files modified:** src/hdmi_exfil/prng.py
- **Verification:** `python -c "from hdmi_exfil.prng import choose_indices"` succeeds
- **Committed in:** 3925d9d

**2. [Rule 1 - Bug] test_prng.py JS cross-language test used stale vectors**
- **Found during:** Task 2 (Integration)
- **Issue:** test_choose_indices_match_js compared against pre-generated JS vectors using old ad-hoc distribution; 317 mismatches expected after RSD switch
- **Fix:** Replaced with determinism, range, frozenset, and K=1 tests; JS vectors will be regenerated in plan 05-03
- **Files modified:** tests/test_prng.py
- **Verification:** All 9 PRNG tests pass
- **Committed in:** 3925d9d

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both auto-fixes necessary for correct operation. No scope creep.

## Issues Encountered
None beyond the deviations documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- RSD module ready for use by plan 05-02 (online estimation / adaptive parameters)
- JS sender (plan 05-03) must be updated to match Python RSD for cross-language compatibility
- All fountain round-trip tests confirm RSD produces recoverable encodings

---
*Phase: 05-fountain-code-optimization*
*Completed: 2026-02-17*
