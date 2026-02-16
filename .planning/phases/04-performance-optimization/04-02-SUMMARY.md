---
phase: 04-performance-optimization
plan: 02
subsystem: protocols
tags: [numba, njit, xor, numpy, fountain, jit-compilation]

# Dependency graph
requires:
  - phase: 04-01
    provides: "3bpp fountain encoding with PAYLOAD_SIZE=12138"
  - phase: 04-03
    provides: "numba >= 0.60.0 pre-installed as dependency"
provides:
  - "Numba @njit-compiled xor_into function (nogil=True)"
  - "FountainDecoder using numpy uint8 arrays instead of bytearray"
  - "warmup() helper for pre-compilation during initialization"
affects: [04-05-integration, fountain-decode-pipeline, sender-encode-loop]

# Tech tracking
tech-stack:
  added: []
  patterns: ["@njit(nogil=True) for GIL-releasing JIT compilation", "np.frombuffer().copy() at ingestion boundary for Numba compatibility"]

key-files:
  created:
    - src/hdmi_exfil/protocols/xor_ops.py
    - tests/test_xor_ops.py
  modified:
    - src/hdmi_exfil/protocols/fountain.py

key-decisions:
  - "xor_into uses element-wise loop (not numpy vectorized) to leverage Numba nogil for GIL release during threaded capture"
  - "Conversion from bytearray to np.ndarray happens at add_droplet boundary, not inside xor_into"
  - "get_file_data uses .tobytes() on numpy chunks before extending bytearray output"

patterns-established:
  - "Numba boundary pattern: convert Python types to numpy at function entry, keep numpy internally"
  - "warmup() pattern: call JIT functions with tiny arrays during init to avoid first-call latency"

# Metrics
duration: 3min
completed: 2026-02-16
---

# Phase 4 Plan 2: Numba XOR Acceleration Summary

**Numba @njit(nogil=True) xor_into replacing Python byte-by-byte XOR loops in FountainDecoder with numpy uint8 array storage**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-16T22:45:51Z
- **Completed:** 2026-02-16T22:48:35Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `xor_ops.py` with `@njit(nogil=True)` XOR function that releases the GIL for concurrent capture thread operation
- Converted FountainDecoder internal storage from `dict[int, bytearray]` to `dict[int, np.ndarray]` (Numba requirement)
- Replaced all Python byte-by-byte XOR loops in `add_droplet()` and `resolve_chunk()` with `xor_into()` calls
- Added warmup() helper to pre-trigger JIT compilation during initialization
- All 84 existing tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create xor_ops.py with Numba-accelerated XOR** - `49e8bdf` (feat)
2. **Task 2: Integrate xor_into into FountainDecoder and add tests** - `b71bb21` (feat)

## Files Created/Modified

- `src/hdmi_exfil/protocols/xor_ops.py` - Numba @njit xor_into function and warmup helper
- `src/hdmi_exfil/protocols/fountain.py` - FountainDecoder converted to numpy arrays + xor_into
- `tests/test_xor_ops.py` - 5 tests: basic XOR, identity, large array, decoder integration, warmup

## Decisions Made

- Used element-wise `@njit` loop instead of numpy vectorized `a ^= b` because `nogil=True` allows GIL release during execution, enabling the threaded capture pipeline to run concurrently
- Conversion from `bytearray`/`bytes` to `np.ndarray` happens at `add_droplet()` entry via `np.frombuffer(data, dtype=np.uint8).copy()`, keeping the public API accepting `bytes | bytearray`
- `get_file_data()` returns `bytearray` (unchanged API) using `.tobytes()` on each numpy chunk

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Numba XOR integration complete; fountain decoder hot path is now JIT-compiled
- All four independent optimization plans (04-01 3bpp, 04-02 Numba XOR, 04-03 PygameRenderer, 04-04 ThreadedCapture) are complete
- Ready for 04-05 integration plan (wiring all optimizations into CLI send/receive)

---
*Phase: 04-performance-optimization*
*Completed: 2026-02-16*
