---
phase: 04-performance-optimization
plan: 01
subsystem: protocols
tags: [fountain, 3bpp, encoding, rgb-binary, capacity]

# Dependency graph
requires:
  - phase: 03-architecture-refactor
    provides: "FountainProtocol class, EncodingProtocol ABC, config module with BLOCKS_PER_FRAME"
provides:
  - "3bpp fountain encode/decode (12138 bytes/frame payload, 3x capacity increase)"
  - "FOUNTAIN_BYTES_PER_FRAME=12150, PAYLOAD_SIZE=12138 constants"
  - "Round-trip tests confirming 3bpp fountain correctness"
affects: [04-02, 04-05, 05-fountain-optimization]

# Tech tracking
tech-stack:
  added: []
  patterns: ["3bpp RGB binary encoding shared between sequential and fountain protocols"]

key-files:
  created:
    - tests/test_fountain_3bpp.py
  modified:
    - src/hdmi_exfil/protocols/fountain.py

key-decisions:
  - "Fountain PAYLOAD_SIZE updated from 4038 to 12138 (3x via RGB binary encoding)"
  - "Fountain encode/decode now uses identical 3bpp pattern as SequentialProtocol"
  - "FountainDecoder left unchanged -- operates on raw bytes, not pixels"

patterns-established:
  - "3bpp encoding: both protocols now use same bit-packing (unpackbits -> reshape(N,3) -> *255)"
  - "3bpp decoding: both protocols threshold all 3 RGB channels (not just green)"

# Metrics
duration: 3min
completed: 2026-02-16
---

# Phase 4 Plan 1: 3bpp Fountain Encoding Upgrade Summary

**Fountain protocol upgraded from 1bpp black/white to 3bpp RGB binary encoding, tripling per-frame payload from 4,038 to 12,138 bytes**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-16T22:38:35Z
- **Completed:** 2026-02-16T22:41:38Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Tripled fountain per-frame data capacity from 4,038 to 12,138 bytes (3x)
- Unified encoding pattern: both sequential and fountain now use identical 3bpp RGB binary encoding
- Full pipeline verified: encode -> sample -> decode -> peel recovers original data with 3bpp

## Task Commits

Each task was committed atomically:

1. **Task 1: Upgrade fountain.py to 3bpp encoding** - `4f1b606` (feat)
2. **Task 2: Add 3bpp fountain round-trip tests** - `f152978` (test)

## Files Created/Modified
- `src/hdmi_exfil/protocols/fountain.py` - Updated capacity constants, encode_frame (3bpp RGB), decode_frame (3-channel threshold)
- `tests/test_fountain_3bpp.py` - 4 round-trip tests: constants, frame shape, encode/decode, full pipeline

## Decisions Made
- Fountain PAYLOAD_SIZE updated from 4038 to 12138 -- same 3bpp formula as sequential: `(ROWS * COLS * 3) // 8 - HEADER_SIZE`
- FountainDecoder left unchanged -- it operates on raw byte payloads, not pixel encoding, so 3bpp is transparent to it
- Existing fountain tests continue to pass because they test the decoder (byte-level XOR/peel), not the pixel encoding path

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Fountain protocol now has 3x capacity, ready for Numba XOR acceleration (04-02)
- All 72 tests pass (+ 1 skipped hardware test), no regressions
- The 3bpp encoding pattern is now shared infrastructure -- future optimizations apply to both protocols

---
*Phase: 04-performance-optimization*
*Completed: 2026-02-16*
