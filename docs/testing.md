# Testing Guide

## Test Suite Overview

The test suite is organized in three levels:

| Level | Hardware | What it tests |
|-------|----------|---------------|
| **Unit tests** | None | Encode/decode, PRNG, fountain math, profiles, XOR ops |
| **Loopback tests** | Elgato on same PC | Full pipeline through real capture card |
| **Integration tests** | 2 PCs + HDMI cable | Production end-to-end transfer |

## Running Tests

### All unit tests (no hardware)

```bash
pytest
```

This runs ~300 tests covering sequential/fountain encode/decode, PRNG determinism, profile math, calibration patterns, threaded capture, and property-based tests.

### Exclude slow tests

```bash
pytest -k "not slow"
```

Slow tests include fountain overhead benchmarks at large K values (K>=500).

### Verbose output

```bash
pytest -v
```

### Specific test file

```bash
pytest tests/test_profiles.py -v
pytest tests/test_fountain.py -v
pytest tests/test_calibration.py -v
```

### Hardware tests (requires Elgato)

```bash
pytest --hardware
```

The `--hardware` flag enables tests marked with `@pytest.mark.hardware`. These require an Elgato capture card connected. Without the flag, hardware tests are automatically skipped.

### Full suite with all markers

```bash
pytest --hardware -v
```

## Test Files Reference

| File | What it tests |
|------|---------------|
| `test_sequential.py` | Sequential protocol encode/decode round-trips |
| `test_fountain.py` | Fountain protocol basics, droplet generation |
| `test_fountain_3bpp.py` | 3-bit-per-block fountain encoding |
| `test_fountain_ge.py` | Gaussian elimination fallback decoder |
| `test_fountain_overhead.py` | Overhead ratio at various K values |
| `test_rsd.py` | Robust Soliton Distribution math |
| `test_rsd_cross_language.py` | Python/JS PRNG + RSD parity |
| `test_prng.py` | SplitMix32 determinism and distribution |
| `test_profiles.py` | ResolutionProfile derived values, protocol injection |
| `test_properties.py` | Property-based tests (hypothesis) for arbitrary data |
| `test_xor_ops.py` | Numba XOR operations |
| `test_calibration.py` | Test pattern generation, SNR computation, benchmark |
| `test_threaded_capture.py` | Ring buffer threaded capture |
| `test_pygame_renderer.py` | Pygame SDL2 renderer |
| `test_loopback.py` | End-to-end loopback via Elgato (hardware) |

## pytest Markers

Configured in `pyproject.toml`:

- **`hardware`** -- Requires Elgato capture card. Skipped unless `--hardware` passed.
- **`slow`** -- Takes >10 seconds (fountain overhead benchmarks at K>=500).

## Writing New Tests

Tests import from the package:

```python
from hdmi_exfil.protocols.sequential import SequentialProtocol
from hdmi_exfil.protocols.fountain import FountainProtocol, FountainDecoder
from hdmi_exfil.config import PROFILES, ResolutionProfile
from hdmi_exfil.prng import splitmix32, choose_indices
```

Example encode/decode round-trip test:

```python
def test_sequential_roundtrip():
    proto = SequentialProtocol()
    data = b"hello world" + b"\x00" * (proto.bytes_per_frame - 11)
    frame = proto.encode_frame(data, frame_index=0, total_frames=1)
    result = proto.decode_frame(frame)
    assert result.data[:11] == b"hello world"
```

## Known Issues

- `test_xor_ops.py::test_fountain_decoder_with_numba` has a pre-existing intermittent failure related to Numba JIT warmup. Not a regression.
