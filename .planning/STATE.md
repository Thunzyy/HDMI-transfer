# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-16)

**Core value:** Maximum throughput data transfer over HDMI without leaving any trace on the source machine.
**Current focus:** Phase 2 in progress — protocol foundation

## Current Position

Phase: 2 of 6 (Protocol Foundation)
Plan: 1 of 5 in current phase
Status: In progress
Last activity: 2026-02-16 -- Completed 02-01-PLAN.md (sequential frame protocol headers)

Progress: [████░░░░░░░░░░░░░░░░░░░░░░░░░░░] 4/31 (13%)

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: 12min
- Total execution time: 49min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-test-foundation | 3/3 | 45min | 15min |
| 02-protocol-foundation | 1/5 | 4min | 4min |

**Recent Trend:**
- Last 5 plans: 01-01 (2min), 01-02 (14min), 01-03 (29min), 02-01 (4min)
- Trend: 02-01 fast -- straightforward header format change with backward-compatible API

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 6-phase strict sequential dependency chain (tests -> protocol -> architecture -> performance -> fountain -> UX)
- [Roadmap]: Test foundation first -- cannot safely refactor without test safety net around working prototype
- [01-01]: ctypes.wintypes imports fine on Linux -- no sender.py patching needed for test imports
- [01-01]: Empty data encode/decode returns (None, None, None, None) -- tested and confirmed as edge case
- [01-02]: chooseIndices has infinite-loop bug when degree > K -- capped in test helpers, production fix deferred
- [01-02]: Fountain test helpers skip seeds that would hang FountainDecoder.add_droplet (degree > K workaround)
- [01-02]: PRNG |0 operator confirmed harmless -- Python/JS produce identical output for 1028 seeds
- [01-03]: Used 256-byte fountain payload for property tests (vs 4044 production) -- same codec logic, 100x faster
- [01-03]: Removed incorrect @pytest.mark.hardware from in-memory test_loopback
- [01-03]: Added GUI availability check for headless environments in hardware test
- [02-01]: Header format >HBIIH: magic(2)+type(1)+index(4)+total(4)+data_len(2)=13 pre-CRC + 4 CRC32 = 17 bytes
- [02-01]: CRC32 computed over pre-CRC header + payload; frame_type defaults to FRAME_TYPE_DATA for backward compat
- [02-01]: BYTES_PER_FRAME auto-recalculated from 12138 to 12133 (5 fewer payload bytes per frame)
- [02-01]: decode_frame does not return frame_type yet -- not needed until Plan 03 lifecycle FSM

### Pending Todos

None.

### Blockers/Concerns

- ~~Existing test_loopback.py has wrong function signatures (TEST-01) -- must fix before relying on tests~~ RESOLVED in 01-01
- ~~Python PRNG may have bug (meaningless |0 operator copied from JS) -- verify with cross-language test vectors early (planned for 01-02)~~ RESOLVED in 01-02: confirmed identical output for 1028 seeds
- **OPEN:** chooseIndices infinite-loop bug when degree > K (affects sender.html and receiver_fountain.py) -- must fix in Phase 2 or Phase 5

## Session Continuity

Last session: 2026-02-16T10:21:54Z
Stopped at: Completed 02-01-PLAN.md (sequential frame protocol headers)
Resume file: None
