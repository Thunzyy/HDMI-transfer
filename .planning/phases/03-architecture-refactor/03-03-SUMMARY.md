---
phase: 03-architecture-refactor
plan: 03
subsystem: protocol
tags: [sequential, encode, decode, abc, strategy-pattern, crc32, numpy]

# Dependency graph
requires:
  - phase: 03-02
    provides: "EncodingProtocol ABC, FrameResult dataclass, sampler module"
  - phase: 02-01
    provides: "Sequential header format, CRC32 verification, frame types"
provides:
  - "SequentialProtocol class implementing EncodingProtocol ABC"
  - "TransferState enum for sequential transfer lifecycle"
  - "Protocol registry with get_protocol factory function"
affects: [03-05, 03-06, 03-07, 04-performance, 06-ux]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Strategy pattern via ABC + registry", "Legacy compatibility wrapper (decode_frame_legacy)"]

key-files:
  created:
    - "src/hdmi_exfil/protocols/sequential.py"
  modified:
    - "src/hdmi_exfil/protocols/__init__.py"

key-decisions:
  - "TransferState uses Enum with auto() instead of plain class with string constants (receiver.py pattern)"
  - "decode_frame_legacy wraps decode_frame internally for backward-compat 4-tuple returns"
  - "encode_frame omits sys.stdout progress output (UI concern belongs in CLI layer)"

patterns-established:
  - "Protocol implementation pattern: inherit EncodingProtocol, implement encode_frame/decode_frame/name/bytes_per_frame"
  - "Protocol-specific helpers as regular methods (encode_start_frame etc.) not part of ABC"
  - "Registry pattern: PROTOCOLS dict + get_protocol(name, **kwargs) factory"

# Metrics
duration: 5min
completed: 2026-02-16
---

# Phase 03 Plan 03: Sequential Protocol Summary

**SequentialProtocol wrapping sender/receiver encode/decode behind EncodingProtocol ABC with protocol registry**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-16T13:57:07Z
- **Completed:** 2026-02-16T14:02:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- SequentialProtocol class implementing full EncodingProtocol ABC with encode_frame/decode_frame matching sender.py/receiver.py byte-for-byte
- TransferState enum (START_PENDING, RECEIVING, COMPLETE) extracted from receiver.py lifecycle
- Protocol registry with get_protocol() factory dispatching by name with ValueError on unknown
- Legacy backward-compat decode_frame_legacy returning old 4-tuple format

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement SequentialProtocol class** - `458d391` (feat)
2. **Task 2: Create protocol registry** - already committed by parallel 03-04 plan (`47f6030`); changes merged cleanly

**Plan metadata:** (pending)

## Files Created/Modified
- `src/hdmi_exfil/protocols/sequential.py` - SequentialProtocol with encode/decode, START/END helpers, TransferState enum (265 lines)
- `src/hdmi_exfil/protocols/__init__.py` - Protocol registry with PROTOCOLS dict and get_protocol factory

## Decisions Made
- **TransferState as Enum:** Used `Enum` with `auto()` values instead of mirroring receiver.py's plain class with string constants. Provides type safety and prevents invalid states.
- **Legacy compatibility:** Added `decode_frame_legacy` method that wraps `decode_frame` and returns old `(frame_index, total_frames, data, data_len)` tuple for gradual migration.
- **No UI in protocol:** `encode_frame` omits the `sys.stdout.write` progress line from sender.py. Progress output is a CLI/UI concern, not a protocol concern.

## Deviations from Plan

None - plan executed exactly as written. The parallel 03-04 plan had already updated `__init__.py` with both sequential and fountain registrations plus the exact ValueError/kwargs signature specified in this plan. No merge conflict occurred.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SequentialProtocol validates the ABC pattern works end-to-end
- Protocol registry ready for CLI integration (03-05, 03-06)
- Fountain protocol already registered by parallel 03-04 plan
- No blockers for remaining architecture refactor plans

---
*Phase: 03-architecture-refactor*
*Completed: 2026-02-16*
