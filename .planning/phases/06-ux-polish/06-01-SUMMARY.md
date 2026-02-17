---
phase: "06"
plan: "01"
subsystem: "config/protocols"
tags: ["resolution-profiles", "dataclass", "dependency-injection", "backward-compat"]
depends_on:
  requires: ["05-*"]
  provides: ["ResolutionProfile dataclass", "PROFILES dict", "profile-aware protocol constructors"]
  affects: ["06-02", "06-03", "06-04"]
tech_stack:
  added: []
  patterns: ["frozen dataclass with computed properties", "constructor injection with optional default"]
key_files:
  created:
    - "tests/test_profiles.py"
  modified:
    - "src/hdmi_exfil/config.py"
    - "src/hdmi_exfil/protocols/sequential.py"
    - "src/hdmi_exfil/protocols/fountain.py"
decisions:
  - id: "06-01-profiles"
    description: "ResolutionProfile is additive -- existing module-level constants remain independent (not aliased to DEFAULT_PROFILE)"
  - id: "06-01-fount-header"
    description: "_FOUNT_HEADER_SIZE duplicated in config.py (12 bytes) to avoid circular import with fountain.py"
  - id: "06-01-injection"
    description: "Profile injection via optional constructor param (profile=None defaults to DEFAULT_PROFILE)"
metrics:
  duration: "4min"
  completed: "2026-02-17"
  tests_before: 265
  tests_after: 286
---

# Phase 6 Plan 1: Resolution Profiles Summary

**One-liner:** Frozen ResolutionProfile dataclass with speed/balanced/quality presets, injected into SequentialProtocol and FountainProtocol via optional constructor parameter.

## What Was Done

### Task 1: ResolutionProfile Dataclass + PROFILES Dict
Added to `config.py`:
- `ResolutionProfile` frozen dataclass with fields: name, width, height, block_size, target_fps
- Computed properties: cols, rows, blocks_per_frame, bits_per_frame, seq_bytes_per_frame, fount_bytes_per_frame
- Three presets in `PROFILES` dict:
  - `"speed"`: 1920x1080 @ 240fps (seq: 12133 B/frame, fount: 12138 B/frame)
  - `"balanced"`: 1920x1080 @ 60fps (same capacity, lower fps)
  - `"quality"`: 3840x2160 @ 30fps (seq: 48583 B/frame, fount: 48588 B/frame)
- `DEFAULT_PROFILE = PROFILES["speed"]`
- All existing module-level constants (WIDTH, HEIGHT, COLS, ROWS, BYTES_PER_FRAME, etc.) remain unchanged

### Task 2: Protocol Profile Injection
- `SequentialProtocol(profile=None)` -- optional profile parameter, defaults to DEFAULT_PROFILE
- `FountainProtocol(profile=None)` -- same pattern
- `encode_frame` in both protocols now uses `self._profile.cols/rows/width/height/blocks_per_frame` instead of module-level imports
- `decode_frame` sanity check uses `self._profile.seq_bytes_per_frame`
- `get_protocol()` factory already forwards `**kwargs`, so `get_protocol("sequential", profile=p)` works with no changes needed to `__init__.py`
- Module-level `PAYLOAD_SIZE` and `FOUNTAIN_BYTES_PER_FRAME` kept unchanged for CLI sender compatibility (updated in plan 06-03)

### Task 3: Unit Tests
Created `tests/test_profiles.py` with 21 tests:
- Speed/balanced/quality profile derived value verification
- Frozen immutability test
- DEFAULT_PROFILE identity
- Protocol default backward compatibility (bytes_per_frame matches legacy)
- Protocol with quality profile (4K capacity)
- Full encode -> sample -> decode roundtrip with profile injection
- Module-level constant backward compatibility

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Profile system is additive, not replacement | Module-level constants remain for backward compat; profiles are used by protocol classes |
| `_FOUNT_HEADER_SIZE` duplicated in config.py | Avoids circular import (config -> fountain -> config); documented with comment |
| Constructor injection pattern | Clean DI: `SequentialProtocol(profile=p)` rather than global state mutation |
| Keep PAYLOAD_SIZE/FOUNTAIN_BYTES_PER_FRAME | CLI sender still references these directly; deferred to 06-03 |

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

- Before: 265 passed, 3 deselected
- After: 286 passed, 3 deselected (+21 new profile tests)
- Zero regressions

## Next Phase Readiness

Plan 06-01 provides the foundation for:
- **06-02** (CLI flags): Can now wire `--profile speed|balanced|quality` through to protocol constructors
- **06-03** (calibration): Profile-aware calibration uses `profile.cols/rows` for grid dimensions
- **06-04** (benchmarking): Can benchmark across profiles by iterating `PROFILES.values()`
