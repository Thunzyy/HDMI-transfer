---
phase: 02-protocol-foundation
plan: 01
subsystem: protocol
tags: [magic-number, crc32, sequential-frames, struct-pack, zlib]

# Dependency graph
requires:
  - phase: 01-test-foundation
    provides: sequential encode/decode tests, loopback test, property-based tests
provides:
  - Protocol constants (SEQ_MAGIC, FOUNTAIN_MAGIC, frame types, header format)
  - Self-describing sequential frames with magic number identification
  - CRC32 integrity checking on encode/decode
  - Backward-compatible encode_frame/decode_frame API
affects: [02-02 (fountain headers), 02-03 (lifecycle FSM), 02-04 (error recovery), 02-05 (integration)]

# Tech tracking
tech-stack:
  added: [zlib (CRC32)]
  patterns: [magic-number protocol identification, CRC32 integrity verification, struct.pack big-endian header format]

key-files:
  created: []
  modified: [common.py, sender.py, receiver.py, tests/test_sequential.py]

key-decisions:
  - "Header format >HBIIH: magic(2) + type(1) + index(4) + total(4) + data_len(2) = 13 pre-CRC + 4 CRC = 17 bytes"
  - "CRC32 computed over pre-CRC header + payload (not over CRC field itself)"
  - "frame_type defaults to FRAME_TYPE_DATA for backward compatibility with existing callers"
  - "decode_frame does not return frame_type to callers (not needed until Plan 03 lifecycle FSM)"

patterns-established:
  - "Protocol routing via magic number: SEQ_MAGIC=0xDA7A for sequential, FOUNTAIN_MAGIC=0xF0C0 reserved"
  - "Integrity checking: CRC32 over header+payload, rejection returns (None, None, None, None)"
  - "Backward-compatible API evolution: new params with defaults, same return signature"

# Metrics
duration: 4min
completed: 2026-02-16
---

# Phase 2 Plan 1: Sequential Frame Protocol Headers Summary

**17-byte protocol headers with magic number 0xDA7A identification and CRC32 integrity checking on sequential encode/decode pipeline**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-16T10:18:17Z
- **Completed:** 2026-02-16T10:21:54Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Sequential frames are now self-describing protocol units with magic number 0xDA7A
- CRC32 integrity checking detects corrupted headers and payloads (rejects as None)
- All 40 existing tests pass with zero modifications (backward-compatible API)
- 9 new protocol-aware tests cover magic rejection, CRC integrity, and frame type roundtrip

## Task Commits

Each task was committed atomically:

1. **Task 1: Add protocol constants to common.py** - `b711451` (feat)
2. **Task 2: Update encode_frame/decode_frame with protocol header** - `a22d0bf` (feat)
3. **Task 3: Add protocol-aware tests** - `5b38ab7` (test)

## Files Created/Modified
- `common.py` - Added SEQ_MAGIC, FOUNTAIN_MAGIC, FRAME_TYPE_*, SEQ_HEADER_FMT, SEQ_HEADER_PRE_CRC, SEQ_CRC_SIZE; changed HEADER_SIZE from 12 to 17
- `sender.py` - Added zlib import; replaced encode_frame with magic+type+CRC32 header; added frame_type param with default FRAME_TYPE_DATA
- `receiver.py` - Added zlib import; replaced decode_frame with magic check + CRC32 verification
- `tests/test_sequential.py` - Added TestMagicNumberRejection (4 tests) and TestCRC32Integrity (5 tests)

## Decisions Made
- Header format `>HBIIH` packs magic(2) + type(1) + index(4) + total(4) + data_len(2) = 13 bytes pre-CRC, plus 4-byte CRC32 = 17 total
- CRC32 is computed over pre-CRC header bytes concatenated with payload bytes (standard approach)
- frame_type is not returned by decode_frame yet -- callers don't need it until Plan 03 adds lifecycle FSM
- BYTES_PER_FRAME auto-recalculated from 12138 to 12133 (5 fewer payload bytes per frame due to larger header)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Protocol constants and header format established for all subsequent Phase 2 plans
- Plan 02 (fountain headers) can now use FOUNTAIN_MAGIC=0xF0C0 for protocol routing
- Plan 03 (lifecycle FSM) can use FRAME_TYPE_START/DATA/END constants
- All tests green (40 passed, 1 deselected hardware)

---
*Phase: 02-protocol-foundation*
*Completed: 2026-02-16*
