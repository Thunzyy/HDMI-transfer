# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-16)

**Core value:** Maximum throughput data transfer over HDMI without leaving any trace on the source machine.
**Current focus:** Phase 3 Architecture Refactor -- foundation modules created

## Current Position

Phase: 3 of 6 (Architecture Refactor)
Plan: 2 of 7 in current phase
Status: In progress
Last activity: 2026-02-16 -- Completed 03-02-PLAN.md (foundation modules)

Progress: [██████████░░░░░░░░░░░░░░░░░░░░░] 10/31 (32%)

## Performance Metrics

**Velocity:**
- Total plans completed: 10
- Average duration: 7min
- Total execution time: 69min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-test-foundation | 3/3 | 45min | 15min |
| 02-protocol-foundation | 5/5 | 19min | 4min |
| 03-architecture-refactor | 2/7 | 5min | 3min |

**Recent Trend:**
- Last 5 plans: 02-03 (4min), 02-04 (4min), 02-05 (3min), 03-01 (2min), 03-02 (3min)
- Trend: Foundation module extraction fast -- algorithms already verified in Phase 1-2

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 6-phase strict sequential dependency chain (tests -> protocol -> architecture -> performance -> fountain -> UX)
- [01-01]: ctypes.wintypes imports fine on Linux -- no sender.py patching needed for test imports
- [01-01]: Empty data encode/decode returns (None, None, None, None) -- tested and confirmed as edge case
- [01-02]: PRNG |0 operator confirmed harmless -- Python/JS produce identical output for 1028 seeds
- [02-01]: Header format >HBIIH: magic(2)+type(1)+index(4)+total(4)+data_len(2)=13 pre-CRC + 4 CRC32 = 17 bytes
- [02-01]: CRC32 computed over pre-CRC header + payload; frame_type defaults to FRAME_TYPE_DATA for backward compat
- [02-01]: BYTES_PER_FRAME auto-recalculated from 12138 to 12133 (5 fewer payload bytes per frame)
- [02-02]: chooseIndices bugfix applied -- degree capped to min(degree, K) in both JS and Python
- [02-02]: Fountain header: magic(2)+seed(4)+K(2)+crc32(4)=12 bytes, PAYLOAD_SIZE=4038
- [02-03]: decode_frame_full (5-tuple with frame_type) added alongside decode_frame (4-tuple)
- [02-03]: START payload: [4B file_size][32B SHA-256][2B name_len][NB name]
- [02-04]: Fountain metadata format matches sequential START: [4B file_size][32B SHA-256][2B name_len][NB name][content]
- [02-05]: route_frame uses lazy import of receiver_fountain constants to avoid circular imports
- [03-01]: Build backend: setuptools.build_meta with src-layout packaging
- [03-01]: constants.json stores magic numbers as decimal (55930, 61632) for cross-language compat
- [03-01]: Frame types in config.py not constants.json (protocol-specific, not encoding params)
- [03-02]: choose_indices returns frozenset (hashable for caching), not set
- [03-02]: Leaf modules (prng, sampler, metadata) import only stdlib+numpy, never config
- [03-02]: FrameResult is frozen+slots dataclass for immutability and memory efficiency
- [03-02]: cv2 import is lazy in sampler (only needed for resize path)

### Pending Todos

None.

### Blockers/Concerns

All prior blockers resolved. No new concerns.

## Session Continuity

Last session: 2026-02-16T13:54:38Z
Stopped at: Completed 03-02-PLAN.md (foundation modules)
Resume file: None
