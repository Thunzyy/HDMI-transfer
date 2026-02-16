# Phase 3 Plan 4: Fountain Protocol Implementation Summary

**One-liner:** FountainProtocol (1-bit-per-block LT-code) and FountainDecoder behind EncodingProtocol ABC, completing strategy pattern with both protocols in registry.

## Metadata

- **Phase:** 03-architecture-refactor
- **Plan:** 04
- **Duration:** ~3min (13:57:44Z to 14:01:13Z)
- **Completed:** 2026-02-16
- **Subsystem:** protocols
- **Tags:** fountain, lt-codes, protocol, strategy-pattern

## Dependency Graph

- **Requires:** 03-01 (package structure), 03-02 (prng, sampler, base ABC)
- **Provides:** FountainProtocol, FountainDecoder, protocol registry with both protocols
- **Affects:** 03-05 (sender/receiver refactor will use get_protocol), 05-fountain (performance)

## Tasks Completed

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Implement FountainProtocol and FountainDecoder | 20a9f56 | src/hdmi_exfil/protocols/fountain.py |
| 2 | Update protocol registry with fountain | 47f6030 | src/hdmi_exfil/protocols/__init__.py |

## What Was Built

### FountainProtocol (src/hdmi_exfil/protocols/fountain.py)

- **FountainProtocol(EncodingProtocol):** 1-bit-per-block encoding protocol
  - `encode_frame(data, frame_index, total_frames, *, seed=None)`: Builds magic+seed+K header with CRC32, maps to black/white blocks, scales to full resolution via cv2.INTER_NEAREST
  - `decode_frame(sampled_grid)`: Thresholds green channel >128, packs bits, parses header, verifies CRC, returns FrameResult
  - `bytes_per_frame`: Returns PAYLOAD_SIZE (4038)
  - `name`: Returns "fountain"

- **FountainDecoder:** Belief-propagation peeling decoder (migrated from receiver_fountain.py lines 38-131)
  - `add_droplet(seed, data)`: Uses PRNG from hdmi_exfil.prng, on-the-fly peeling
  - `resolve_chunk(chunk_idx, chunk_data)`: Recursive peeling propagation
  - `is_complete()`, `get_file_data()`: Status and reconstruction

- **Constants:** FOUNT_HEADER_FMT='>HIH', FOUNT_HEADER_SIZE=12, FOUNTAIN_BYTES_PER_FRAME=4050, PAYLOAD_SIZE=4038

### Protocol Registry (src/hdmi_exfil/protocols/__init__.py)

- **PROTOCOLS dict:** Maps 'sequential' -> SequentialProtocol, 'fountain' -> FountainProtocol
- **get_protocol(name):** Factory function, clear error on unknown protocol
- **Re-exports:** EncodingProtocol, FrameResult, FountainDecoder, FountainProtocol, SequentialProtocol, TransferState

## Tech Stack

- **Patterns:** Strategy pattern (protocol registry), ABC inheritance
- **Dependencies:** numpy (bit packing), cv2 (lazy import for resize), zlib (CRC32), struct (header parsing)

## Key Files

### Created

| File | Purpose | Lines |
|------|---------|-------|
| src/hdmi_exfil/protocols/fountain.py | FountainProtocol + FountainDecoder | 296 |

### Modified

| File | Change |
|------|--------|
| src/hdmi_exfil/protocols/__init__.py | Added registry with both protocols, get_protocol factory, re-exports |

## Verification Results

- FountainDecoder recovers K=3 chunks from 3 degree-1 droplets
- FountainProtocol round-trip: encode_frame -> sample_frame -> decode_frame returns is_valid=True with correct seed (42) and K (3)
- get_protocol('fountain') returns FountainProtocol instance
- PAYLOAD_SIZE == 4038, FOUNTAIN_BYTES_PER_FRAME == 4050
- All 58 existing tests pass (1 skipped -- loopback display test)

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Fountain constants in fountain.py, not config.py | Protocol-specific constants belong with the protocol implementation |
| cv2 imported lazily in encode_frame | Matches sampler pattern; not needed at module level |
| Registry includes both protocols despite 03-03 running in parallel | sequential.py exists on disk from parallel agent; registry works now |
| FountainDecoder uses hdmi_exfil.prng.PRNG not inline | Shared PRNG from 03-02 extraction; single source of truth |

## Deviations from Plan

None -- plan executed exactly as written.

## Next Phase Readiness

Both protocols now live behind the EncodingProtocol ABC with a unified registry. The strategy pattern is complete: `get_protocol('sequential')` and `get_protocol('fountain')` return swappable protocol instances. This unblocks 03-05 (sender/receiver refactor) which will use the registry to select protocols dynamically.
