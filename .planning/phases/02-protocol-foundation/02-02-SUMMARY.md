---
phase: 02-protocol-foundation
plan: 02
subsystem: protocol
tags: [fountain, crc32, magic-number, integrity, bugfix, LT-codes]

# Dependency graph
requires:
  - phase: 01-test-foundation
    provides: fountain test infrastructure (test_fountain.py, test_properties.py)
provides:
  - "Fountain protocol header with magic 0xF0C0 and CRC32 integrity"
  - "chooseIndices infinite-loop bugfix (degree capped to K) in both JS and Python"
  - "Updated fountain tests for 12-byte header format (PAYLOAD_SIZE=4038)"
affects: [02-03, 02-04, 02-05, 05-fountain-optimization]

# Tech tracking
tech-stack:
  added: [zlib.crc32 (stdlib)]
  patterns: ["CRC32 over header[0:8]+payload for integrity", "Magic number 0xF0C0 for frame identification"]

key-files:
  created: []
  modified: [sender.html, receiver_fountain.py, tests/test_fountain.py]

key-decisions:
  - "chooseIndices bugfix applied in this phase (not deferred to Phase 5) since both files were already being modified"
  - "CRC32 computed over header[0:8]+payload (excludes the CRC field itself) -- same scope as sequential protocol"
  - "Fountain constants remain local to fountain files (not in common.py) -- consistent with existing design"

patterns-established:
  - "Fountain frame format: magic(2) + seed(4) + K(2) + crc32(4) + payload = 12-byte header"
  - "CRC32 scope: always header pre-CRC fields + payload (never include the CRC field in its own computation)"

# Metrics
duration: 4min
completed: 2026-02-16
---

# Phase 2 Plan 02: Fountain Protocol Headers Summary

**Fountain frames with 12-byte protocol header (magic 0xF0C0 + CRC32 integrity) and chooseIndices infinite-loop bugfix in both JS sender and Python receiver**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-16T10:18:26Z
- **Completed:** 2026-02-16T10:21:55Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Fountain sender (sender.html) now emits 12-byte protocol headers with magic number 0xF0C0 and per-frame CRC32 integrity
- Fountain receiver (receiver_fountain.py) validates magic and CRC, silently rejecting noise and corrupted frames
- chooseIndices infinite-loop bug fixed in both JS and Python (degree capped to min(degree, K))
- K=1 fountain transfers now work without hanging
- All 13 fountain tests pass (11 unit + 2 property)

## Task Commits

Each task was committed atomically:

1. **Task 1: Update sender.html with CRC32, 12-byte header, chooseIndices bugfix** - `ec27ce5` (feat)
2. **Task 2: Update receiver_fountain.py with header parsing, magic, CRC, bugfix** - `810ea4c` (feat)
3. **Task 3: Update fountain tests for new header format, add bugfix/CRC tests** - `3178e6d` (test)

## Files Created/Modified
- `sender.html` - Added FOUNTAIN_MAGIC, CRC32_TABLE, inline crc32(), 12-byte header in renderLoop, chooseIndices degree cap
- `receiver_fountain.py` - Added FOUNTAIN_MAGIC, FOUNT_HEADER_* constants, magic check, CRC32 verification in main loop, degree cap in add_droplet
- `tests/test_fountain.py` - Updated HEADER_LEN=12, PAYLOAD_SIZE=4038, simplified _fountain_roundtrip (removed _would_hang workaround), added TestChooseIndicesBugfix and TestFountainCRC32

## Decisions Made
- Fixed chooseIndices bug now (Phase 2) rather than deferring to Phase 5 -- both files were already being modified for protocol headers, making this the lowest-risk moment for the fix
- Kept _compute_degree and _would_hang helper functions in test file for reference, though they are no longer called by _fountain_roundtrip
- CRC32 scope matches sequential protocol pattern: header pre-CRC fields + payload

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all changes applied cleanly and all tests passed on first run.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Fountain protocol is now protocol-aware with magic + CRC, matching the sequential protocol capabilities
- The chooseIndices blocker from Phase 1 is resolved -- no longer a concern for future phases
- Ready for Plan 03 (protocol routing / unified receiver) and Plan 04 (fountain metadata extension)

---
*Phase: 02-protocol-foundation*
*Completed: 2026-02-16*
