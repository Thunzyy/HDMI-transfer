---
phase: 03-architecture-refactor
plan: 02
subsystem: encoding
tags: [prng, splitmix32, abc, protocol, sampler, metadata, foundation]

# Dependency graph
requires:
  - phase: 03-01
    provides: "Package scaffold with config.py, constants.json, subpackage __init__.py files"
  - phase: 02-02
    provides: "chooseIndices bugfix (degree capped to K) and fountain header format"
  - phase: 02-03
    provides: "START metadata format [4B file_size][32B SHA-256][2B name_len][NB name]"
provides:
  - "SplitMix32 PRNG class and choose_indices() in hdmi_exfil.prng"
  - "EncodingProtocol ABC and FrameResult dataclass in hdmi_exfil.protocols.base"
  - "Unified sample_frame() in hdmi_exfil.capture.sampler"
  - "Metadata pack/unpack utilities in hdmi_exfil.file_handling.metadata"
affects:
  - 03-03 (sequential protocol implementation imports base ABC + metadata)
  - 03-04 (fountain protocol implementation imports PRNG + base ABC + metadata)
  - 03-05 (routing layer imports protocol ABCs)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure functions with explicit params (no config import in leaf modules)"
    - "frozen dataclass with slots for immutable result types"
    - "ABC with abstractmethod + property for protocol interface"

key-files:
  created:
    - src/hdmi_exfil/prng.py
    - src/hdmi_exfil/protocols/base.py
    - src/hdmi_exfil/capture/sampler.py
    - src/hdmi_exfil/file_handling/metadata.py
  modified:
    - src/hdmi_exfil/protocols/__init__.py

key-decisions:
  - "PRNG uses uppercase hex constants (0x9E3779B9) for readability but produces identical output"
  - "choose_indices returns frozenset (hashable for caching) not set"
  - "sample_frame takes explicit rows/cols/block_size params (config-agnostic, testable)"
  - "FrameResult is frozen+slots dataclass for immutability and memory efficiency"
  - "parse_start_metadata adds name_len>1024 guard matching fountain version"
  - "cv2 import is lazy in sampler (only needed for resize path)"

patterns-established:
  - "Leaf modules import only stdlib + numpy, never hdmi_exfil.config"
  - "Protocol ABC contract: encode_frame, decode_frame, bytes_per_frame, name"
  - "Metadata format shared by sequential START and fountain chunk-0"

# Metrics
duration: 3min
completed: 2026-02-16
---

# Phase 3 Plan 2: Foundation Modules Summary

**SplitMix32 PRNG + EncodingProtocol ABC + unified sampler + metadata pack/unpack as config-agnostic leaf modules**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-16T13:51:27Z
- **Completed:** 2026-02-16T13:54:38Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments

- Extracted SplitMix32 PRNG to standalone module, bit-exact verified against old receiver_fountain.py for seeds [1, 42, 1000, 0xFFFFFFFF] x 100 values each
- Defined EncodingProtocol ABC enforcing encode_frame, decode_frame, bytes_per_frame, name as abstract
- Unified two diverged sample_frame implementations (simple slice vs arange+broadcasting) into single function with optional offset/scale
- Extracted metadata build/parse for both sequential and fountain formats with round-trip verification

## Task Commits

Each task was committed atomically:

1. **Task 1: Create PRNG module and EncodingProtocol ABC** - `7b20d30` (feat)
2. **Task 2: Create unified sampler and metadata modules** - `d2922e2` (feat)

## Files Created/Modified

- `src/hdmi_exfil/prng.py` - SplitMix32 PRNG class and choose_indices function
- `src/hdmi_exfil/protocols/base.py` - EncodingProtocol ABC and FrameResult dataclass
- `src/hdmi_exfil/protocols/__init__.py` - Subpackage docstring added
- `src/hdmi_exfil/capture/sampler.py` - Unified block-centre sampling for captured frames
- `src/hdmi_exfil/file_handling/metadata.py` - Metadata pack/unpack for START and fountain formats

## Decisions Made

- **frozenset for choose_indices return:** Hashable for use as dict key or in caching decorators. Plan specified this.
- **Lazy cv2 import in sampler:** Only imported when frame resize is needed, avoiding hard dependency on opencv for unit tests that pass correct-sized arrays.
- **name_len > 1024 guard in parse_start_metadata:** Added to match the defensive check already present in parse_fountain_metadata (receiver_fountain.py). This is a [Rule 2 - Missing Critical] deviation -- prevents absurdly large filename allocations.
- **frozen+slots on FrameResult:** Immutable results prevent accidental mutation; slots reduce memory overhead for high-throughput decode loops.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added name_len guard to parse_start_metadata**
- **Found during:** Task 2 (metadata module)
- **Issue:** Old receiver.py parse_start_metadata had no bounds check on filename_len, while receiver_fountain.py had `name_len > 1024` guard
- **Fix:** Added same `name_len > 1024 or 38 + name_len > len(payload)` check to parse_start_metadata
- **Files modified:** src/hdmi_exfil/file_handling/metadata.py
- **Verification:** Edge cases tested, returns (None, None, None) for malformed input
- **Committed in:** d2922e2 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Defensive bounds check for correctness. No scope creep.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All four foundation modules importable and verified
- EncodingProtocol ABC ready for sequential (03-03) and fountain (03-04) implementations
- PRNG + choose_indices ready for fountain protocol module
- Sampler and metadata ready for both protocol implementations
- All 58 existing tests continue to pass (old code untouched)

---
*Phase: 03-architecture-refactor*
*Completed: 2026-02-16*
