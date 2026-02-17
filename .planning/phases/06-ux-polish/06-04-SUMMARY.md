---
phase: "06"
plan: "04"
subsystem: "cli/calibration-benchmark"
tags: ["calibration", "benchmark", "test-patterns", "SNR", "JSON-output", "CLI"]
depends_on:
  requires: ["06-01"]
  provides: ["hdmi-calibrate CLI", "hdmi-bench CLI", "test pattern generator", "SNR computation"]
  affects: []
tech_stack:
  added: []
  patterns: ["dataclass JSON serialization", "in-memory encode/decode roundtrip benchmark", "block-centre SNR computation"]
key_files:
  created:
    - "src/hdmi_exfil/display/test_patterns.py"
    - "src/hdmi_exfil/cli/calibrate.py"
    - "src/hdmi_exfil/cli/benchmark.py"
    - "tests/test_calibration.py"
  modified:
    - "pyproject.toml"
decisions:
  - id: "06-04-bw-only"
    description: "Checkerboard uses only black (0,0,0) and white (255,255,255) for chroma subsampling robustness"
  - id: "06-04-snr-60"
    description: "Perfect capture returns 60.0 dB SNR (capped when noise < 1e-6)"
  - id: "06-04-bench-inmemory"
    description: "Benchmark runs encode/sample/decode in-memory (no display or capture hardware needed)"
metrics:
  duration: "4min"
  completed: "2026-02-17"
  tests_before: 286
  tests_after: 296
---

# Phase 6 Plan 4: Calibration and Benchmark CLI Summary

**One-liner:** B&W-only calibration test patterns with SNR/alignment analysis (hdmi-calibrate) and in-memory encode/decode throughput benchmarks with JSON output (hdmi-bench).

## What Was Done

### Task 1: Test Pattern Generator and Calibration CLI

Created `src/hdmi_exfil/display/test_patterns.py` with four functions:
- `generate_checkerboard(profile)` -- creates a pure B&W alternating block pattern that survives chroma subsampling (4:2:0, 4:2:2). Uses `np.repeat` for upscaling (no cv2 dependency).
- `generate_known_payload(profile)` -- encodes 0xAA-filled payload via SequentialProtocol for realistic roundtrip testing.
- `compute_snr(captured, expected, block_size)` -- samples block centres, splits into white/black populations, computes 20*log10(signal/noise) in dB. Returns 60.0 for perfect captures.
- `compute_alignment(captured, expected)` -- uses cv2.matchTemplate on central crops for pixel offset detection.

Created `src/hdmi_exfil/cli/calibrate.py` with three subcommands:
- `hdmi-calibrate send` -- displays checkerboard pattern (cv2 or pygame renderer)
- `hdmi-calibrate recv <source>` -- captures N frames, averages for noise reduction, computes alignment offset and SNR, reports signal quality (EXCELLENT/GOOD/FAIR/POOR thresholds)
- `hdmi-calibrate loopback <source>` -- display + wait 2s + capture + analyze

Registered `hdmi-calibrate = hdmi_exfil.cli.calibrate:main` in pyproject.toml.

### Task 2: Benchmarking CLI with JSON Output

Created `src/hdmi_exfil/cli/benchmark.py` with:
- `BenchmarkResult` dataclass with 9 fields: profile, mode, frames_per_sec, bytes_per_sec, overhead_pct, error_rate, duration_sec, total_frames, total_bytes. Includes `to_json()` method.
- `run_benchmark(profile, mode, payload_size_kb, duration_sec)` dispatches to sequential or fountain benchmark.
- Sequential benchmark: generates random payload, encodes each frame, samples block centres (simulating capture), decodes, counts CRC errors.
- Fountain benchmark: builds K chunks, generates droplets via choose_indices/xor_into, encodes/samples/decodes, feeds to FountainDecoder, measures overhead_pct.
- `hdmi-bench` CLI with `--profile`, `--mode`, `--size`, `--duration`, `--no-json` flags.

Created `tests/test_calibration.py` with 10 tests:
1. `test_checkerboard_shape` -- speed profile returns (1080, 1920, 3) uint8
2. `test_checkerboard_shape_quality` -- quality profile returns (2160, 3840, 3) uint8
3. `test_checkerboard_pattern` -- block (0,0) white, (0,1) black, (1,0) black, (1,1) white
4. `test_checkerboard_only_bw` -- all pixels are 0 or 255 (no intermediate values)
5. `test_snr_perfect_capture` -- self-comparison returns 60.0 dB
6. `test_snr_with_noise` -- gaussian noise (std=30) gives positive SNR below 50 dB
7. `test_snr_heavy_noise` -- heavy noise (std=80) gives SNR below 30 dB
8. `test_benchmark_result_json` -- JSON has all 9 expected keys
9. `test_benchmark_result_json_roundtrip` -- values survive JSON round-trip
10. `test_benchmark_sequential_roundtrip` -- sequential benchmark completes with zero errors

Registered `hdmi-bench = hdmi_exfil.cli.benchmark:main` in pyproject.toml.

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| B&W-only checkerboard (0 and 255 only) | Survives all chroma subsampling modes; no intermediate values to corrupt |
| 60.0 dB cap for perfect captures | Avoids infinity/division-by-zero when noise is zero |
| In-memory benchmark (no hardware) | Measures pure encode/decode throughput; reproducible on any machine |
| Benchmark outputs JSON to stdout | Machine-parseable; human-readable via `--no-json` flag |
| Benchmark status messages go to stderr | Separates progress from structured output |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed checkerboard generating (H, W, 1) instead of (H, W, 3)**
- **Found during:** Task 1 verification
- **Issue:** `np.where(mask[:,:,None], np.uint8(255), np.uint8(0))` produced (H,W,1) because scalar broadcast collapsed the channel dimension
- **Fix:** Used explicit `np.array([255,255,255], dtype=np.uint8)` and `np.array([0,0,0], dtype=np.uint8)` as where arguments
- **Files modified:** `src/hdmi_exfil/display/test_patterns.py`
- **Commit:** 1cc2bfb

## Test Results

- Before: 286 passed, 3 deselected
- After: 296 passed, 3 deselected (+10 new calibration/benchmark tests)
- Zero regressions

## Next Phase Readiness

Plan 06-04 is the final plan in Phase 6 (UX and Polish). All four plans in the phase are now complete:
- 06-01: Resolution profiles
- 06-02: JS sender 3bpp encoding
- 06-03: (previously completed)
- 06-04: Calibration and benchmark CLI

The project is feature-complete across all 6 phases.
