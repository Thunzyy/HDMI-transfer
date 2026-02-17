---
phase: 05-fountain-code-optimization
plan: 03
subsystem: protocols
tags: [fountain, rsd, cross-language, javascript, sender, redundancy, determinism]

# Dependency graph
requires:
  - phase: 05-fountain-code-optimization
    plan: 01
    provides: "degree.py (robust_soliton_cdf, sample_degree), RSD-based choose_indices"
provides:
  - "Python sender using RSD via choose_indices (no ad-hoc distribution)"
  - "JavaScript sender using identical RSD (robustSolitonCdf, sampleDegree)"
  - "--fountain-redundancy CLI flag for controlled droplet count"
  - "138 cross-language determinism tests (Python == JS for all (seed, K) vectors)"
affects:
  - "05-04: Both senders now use RSD; any future encoding changes need both updated"
  - "06-*: UX/Polish phase can safely add JS 3bpp encoding (RSD math already correct)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cross-language determinism testing via Node.js subprocess from pytest"
    - "bisect_left-equivalent binary search in JavaScript for CDF sampling"
    - "Single PRNG call for degree sampling (one next_float in Python, one next()/2^32 in JS)"

key-files:
  created:
    - "tests/test_rsd_cross_language.py"
  modified:
    - "src/hdmi_exfil/cli/send.py"
    - "web/sender.template.html"
    - "sender.html"
    - "tests/test_fountain_3bpp.py"

key-decisions:
  - "New --fountain-redundancy float flag (separate from existing --redundancy int for sequential)"
  - "Python sender uses choose_indices() directly (not raw PRNG + degree logic) for single-source-of-truth"
  - "JS sampleDegree uses (lo+hi)>>1 binary search matching Python bisect.bisect_left"
  - "JS 3bpp encoding left for future UX phase (RSD math is encoding-independent)"

patterns-established:
  - "Cross-language test pattern: generate vectors in Python, run JS via Node.js subprocess, compare"
  - "All degree distribution logic flows from degree.py (Python) / robustSolitonCdf (JS) -- no more inline distributions"

# Metrics
duration: 8min
completed: 2026-02-17
---

# Phase 5 Plan 3: RSD Port to Senders + Cross-Language Tests Summary

**RSD ported to both Python CLI and JS browser senders, --fountain-redundancy flag, 138 cross-language determinism tests confirming Python == JS for all (seed, K) vectors**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-17T00:06:19Z
- **Completed:** 2026-02-17T00:14:01Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Replaced ad-hoc degree distribution in Python sender with `choose_indices()` (single-source-of-truth via degree.py)
- Added `--fountain-redundancy` float CLI flag: `--fountain-redundancy 1.05` sends `ceil(K * 1.05)` droplets then stops
- Ported RSD to JavaScript: `robustSolitonCdf(K)` and `sampleDegree(cdf, r)` match Python to 15+ decimal places
- Rebuilt sender.html from updated template
- Created 138 cross-language tests: CDF consistency, Python determinism, JS-via-Node.js vectors, distribution shape
- Fixed test_fountain_3bpp.py which was hanging due to stale ad-hoc distribution in test encoder

## Task Commits

Each task was committed atomically:

1. **Python sender RSD + redundancy** - `42ec7cb` (feat)
2. **JavaScript sender RSD port** - `25b2afa` (feat)
3. **Cross-language tests + 3bpp fix** - `6bf3e87` (test)

## Files Created/Modified

- `src/hdmi_exfil/cli/send.py` - Replaced ad-hoc degree with choose_indices, added --fountain-redundancy flag
- `web/sender.template.html` - Added robustSolitonCdf, sampleDegree, updated chooseIndices to use RSD
- `sender.html` - Rebuilt from template with RSD functions
- `tests/test_rsd_cross_language.py` - 138 tests: CDF, determinism, cross-language, distribution shape
- `tests/test_fountain_3bpp.py` - Fixed stale ad-hoc distribution in test encoder (was causing hang)

## Decisions Made

- **--fountain-redundancy as separate flag:** Kept existing `--redundancy` (int) for sequential frame repetition, added `--fountain-redundancy` (float) for fountain droplet limit. Avoids breaking backward compatibility.
- **choose_indices() in sender:** Python sender calls `choose_indices(seed, K)` directly rather than reimplementing degree logic. This ensures single-source-of-truth through degree.py.
- **JS binary search:** `sampleDegree` uses `(lo + hi) >> 1` right-shift binary search matching Python's `bisect.bisect_left` behavior exactly.
- **JS 3bpp deferred:** The JavaScript sender still uses 1bpp encoding (BITS_PER_FRAME = ROWS * COLS). The 3bpp update is independent of RSD math and deferred to UX/Polish phase.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_fountain_3bpp.py using stale ad-hoc degree distribution**
- **Found during:** Task 3 (verification)
- **Issue:** `test_3bpp_fountain_full_roundtrip` built droplets using old ad-hoc distribution (r < 0.1, r < 0.6) while FountainDecoder.add_droplet now uses RSD. Encoder/decoder disagreed on indices, causing the decoder to never complete (test hung forever).
- **Fix:** Replaced inline degree logic with `choose_indices(seed, K)` call in the test
- **Files modified:** tests/test_fountain_3bpp.py
- **Verification:** test_3bpp_fountain_full_roundtrip passes in 2.6s (was previously hanging)
- **Committed in:** 6bf3e87

---

**Total deviations:** 1 auto-fixed (bug in test)
**Impact on plan:** Necessary fix -- test was broken since 05-01 RSD migration.

## Issues Encountered

None beyond the deviation documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both senders (Python CLI and JS browser) now use identical RSD degree distribution
- Cross-language compatibility verified for K values from 1 to 10,000
- --fountain-redundancy flag enables controlled transmission for automated/scripted use
- JS sender still uses 1bpp encoding (3bpp update deferred to UX/Polish phase)
- Plan 05-04 (integration/validation) can proceed with confidence that sender/receiver degree distributions match

---
*Phase: 05-fountain-code-optimization*
*Completed: 2026-02-17*
