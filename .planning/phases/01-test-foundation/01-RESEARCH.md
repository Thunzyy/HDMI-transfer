# Phase 1: Test Foundation - Research

**Researched:** 2026-02-16
**Domain:** Python test infrastructure for binary encode/decode pipeline with cross-language PRNG verification
**Confidence:** HIGH

## Summary

This phase establishes an automated test safety net around a working HDMI data exfiltration prototype. The codebase has two encoding modes: **sequential** (3-bit per block, RGB channels, sender.py/receiver.py) and **fountain** (1-bit per block, black/white, sender.html/receiver_fountain.py with SplitMix32 PRNG). The existing test file (`tests/test_loopback.py`) has two specific bugs: wrong number of arguments to `encode_frame()` and wrong number of return values from `decode_frame()`.

Research confirmed that the Python and JavaScript SplitMix32 PRNG implementations produce **identical output** for all tested seeds. The `(self.a | 0)` line in Python is confirmed as a harmless no-op (in JS, `|0` converts to signed 32-bit int; in Python, bitwise OR with 0 does nothing since `& 0xFFFFFFFF` masking is already applied). The `chooseIndices()` function also produces identical results across both languages. Cross-language test vectors can be generated reliably using Node.js (v20.19.5 available on this system).

The test infrastructure needs: pytest with custom markers for hardware tests, hypothesis for property-based testing, and a conftest.py to handle imports and markers. No pytest config files or conftest.py currently exist in the project.

**Primary recommendation:** Fix the two specific bugs in test_loopback.py, then build out unit tests for both encoding modes, PRNG cross-language vectors (static JSON generated from Node.js), and hypothesis property-based tests -- all runnable without hardware via `pytest` (hardware tests opt-in via `--hardware` flag).

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.4.2 | Test runner and framework | Already installed, industry standard for Python testing |
| hypothesis | 6.151.6 | Property-based testing with binary data strategies | Installed during research; `binary()` strategy perfect for encode/decode fuzzing |
| numpy | 2.3.5 | Array operations for encode/decode | Already used by production code |
| opencv-python-headless | 4.13.0 | Image operations without GUI dependencies | Installed during research; headless avoids X11/display deps in CI |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Node.js | 20.19.5 | Generate JS PRNG test vectors | One-time vector generation for cross-language tests |
| struct (stdlib) | -- | Binary packing/unpacking | Header encoding/decoding in tests |
| json (stdlib) | -- | Store/load test vectors | PRNG cross-language test vector files |
| tempfile (stdlib) | -- | Temporary test files | Avoid test data pollution |
| os (stdlib) | -- | File operations | Test data setup/teardown |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Static JSON vectors | Node.js subprocess at test time | Static vectors are faster, reproducible, and don't require Node.js at test runtime |
| hypothesis `binary()` | Manual random data generation | hypothesis finds edge cases humans miss, provides shrinking for minimal failing examples |
| pytest markers for hardware | Environment variable detection | Markers are explicit, documented, and integrate with pytest CLI (`-m "not hardware"`) |

**Installation:**
```bash
pip install pytest hypothesis opencv-python-headless numpy
```

**requirements-dev.txt** (new file needed):
```
pytest>=8.0
hypothesis>=6.0
opencv-python-headless>=4.0
numpy>=2.0
```

## Architecture Patterns

### Recommended Test Structure
```
tests/
    conftest.py              # Markers, fixtures, path setup
    test_sequential.py       # TEST-02: sequential encode/decode round-trips
    test_fountain.py         # TEST-03: fountain encode/decode round-trips
    test_prng.py             # TEST-04: PRNG cross-language verification
    test_loopback.py         # TEST-01/05: Fixed loopback test (hardware)
    test_properties.py       # TEST-06: hypothesis property-based tests
    data/
        testfile.txt         # Existing test data
        prng_vectors.json    # Generated PRNG test vectors (from Node.js)
```

### Pattern 1: conftest.py with Hardware Marker
**What:** Central test configuration with custom marker for hardware-dependent tests
**When to use:** Every test run -- conftest.py is loaded automatically by pytest
**Example:**
```python
# tests/conftest.py
import sys
import os
import pytest

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def pytest_addoption(parser):
    parser.addoption(
        "--hardware", action="store_true", default=False,
        help="Run tests that require Elgato capture card hardware"
    )

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "hardware: mark test as requiring Elgato capture card"
    )

def pytest_runtest_setup(item):
    if "hardware" in item.keywords and not item.config.getoption("--hardware"):
        pytest.skip("Skipping hardware test: use --hardware to run")
```

### Pattern 2: In-Memory Encode/Decode Round-Trip
**What:** Test encode then decode without any hardware or file I/O
**When to use:** All unit tests for both sequential and fountain modes
**Example:**
```python
# Sequential round-trip pattern
from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import BYTES_PER_FRAME

def test_sequential_roundtrip():
    data = os.urandom(BYTES_PER_FRAME)
    frame = encode_frame(data, 0, 1)  # 3 args: data, index, total
    sampled = sample_frame(frame)
    idx, total, decoded, length = decode_frame(sampled)  # 4 return values
    assert idx == 0
    assert total == 1
    assert decoded == data
```

### Pattern 3: Fountain Round-Trip Without Hardware
**What:** Simulate fountain encoding in Python (mirror JS logic) and decode with FountainDecoder
**When to use:** TEST-03 fountain codec tests
**Example:**
```python
from receiver_fountain import PRNG, FountainDecoder

PAYLOAD_SIZE = 4044  # BYTES_PER_FRAME(4050) - HEADER_LEN(6)

def choose_indices(seed, K):
    prng = PRNG(seed)
    degree = 1
    r = prng.next_float()
    if r < 0.1: degree = 1
    elif r < 0.6: degree = 2
    else: degree = int(prng.next_float() * min(K, 20)) + 1
    indices = set()
    while len(indices) < degree:
        indices.add(prng.next() % K)
    return indices

def build_droplet(seed, K, chunks):
    indices = choose_indices(seed, K)
    payload = bytearray(PAYLOAD_SIZE)
    for idx in indices:
        for i in range(PAYLOAD_SIZE):
            payload[i] ^= chunks[idx][i]
    return payload

# In test: create data, split into chunks, build droplets, feed to decoder
```

### Pattern 4: Static PRNG Test Vectors
**What:** Pre-generate test vectors from Node.js, save as JSON, load in Python tests
**When to use:** TEST-04 cross-language PRNG verification
**Example:**
```javascript
// generate_vectors.js (one-time script)
function createPRNG(seed) {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x9e3779b9) >>> 0;
        let t = a ^ (a >>> 16);
        t = Math.imul(t, 0x21f0aaad) >>> 0;
        t ^= t >>> 15;
        t = Math.imul(t, 0x735a2d97) >>> 0;
        t ^= t >>> 15;
        return t >>> 0;
    };
}
// Generate 1000+ seeds, 10 outputs each, save as JSON
```

```python
# test_prng.py
import json
from receiver_fountain import PRNG

def test_prng_matches_js():
    with open("tests/data/prng_vectors.json") as f:
        vectors = json.load(f)
    for entry in vectors:
        prng = PRNG(entry["seed"])
        for expected in entry["outputs"]:
            assert prng.next() == expected
```

### Anti-Patterns to Avoid
- **Testing through hardware when in-memory suffices:** Encode/decode are pure functions on numpy arrays. Never require a camera for logic tests.
- **Importing entire modules when only functions needed:** `sender.py` has Windows-specific `ctypes.windll` imports at module level that happen to work on Linux but could break. If they do break, extract `encode_frame` to a separate module.
- **Writing test data to working directory:** Use `tempfile` or `tests/data/` to avoid polluting the project root. The existing test writes `test_data.bin` to cwd.
- **Hardcoding magic numbers:** Use constants from `common.py` -- `BYTES_PER_FRAME`, `HEADER_SIZE`, `ROWS`, `COLS`, etc.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Random binary test data | Manual `os.urandom()` with fixed sizes | `hypothesis.strategies.binary(min_size=1, max_size=BYTES_PER_FRAME)` | Hypothesis shrinks failing cases to minimal examples, finds edge cases |
| PRNG vector generation | Manual Python loops to create vectors | Node.js script running exact JS PRNG from sender.html | Must use THE SAME JS code to guarantee vectors are authoritative |
| Test discovery and running | Custom test runner | `pytest` with markers | Pytest handles discovery, filtering, fixtures, reporting |
| Hardware detection | `os.path.exists('/dev/video*')` heuristics | `pytest.mark.hardware` + `--hardware` CLI flag | Explicit opt-in is more reliable than hardware detection heuristics |
| Temp file management | Manual `open/write/delete` | `pytest` `tmp_path` fixture or `tempfile.NamedTemporaryFile` | Automatic cleanup even on test failure |

**Key insight:** The encode/decode functions are pure (data in, data out). All logic correctness can be tested in-memory without any hardware, file I/O, or GUI. The only test that genuinely needs hardware is the Elgato loopback (TEST-05).

## Common Pitfalls

### Pitfall 1: Wrong Function Signatures (THE KNOWN BUG)
**What goes wrong:** `test_loopback.py` calls `encode_frame(chunk, i)` but the actual signature is `encode_frame(data_chunk, frame_index, total_frames)` -- missing the third argument `total_frames`. Also calls `idx, data, length = decode_frame(sampled)` but the actual return is `(frame_index, total_frames, data, data_len)` -- 4 values, not 3.
**Why it happens:** Test was written against an earlier API version and never updated.
**How to avoid:** Fix to `encode_frame(chunk, i, total_frames)` and `idx, total, data, length = decode_frame(sampled)`.
**Warning signs:** `TypeError: encode_frame() missing 1 required positional argument` and `ValueError: not enough values to unpack`.

### Pitfall 2: Sequential vs Fountain Constant Confusion
**What goes wrong:** Using `BYTES_PER_FRAME` from `common.py` (12138, for 3-bit sequential encoding) when testing fountain mode (which uses 4050 bytes per frame with 1-bit encoding and a different header).
**Why it happens:** Fountain encoding uses completely different constants that are defined locally in `sender.html` and `receiver_fountain.py`, not in `common.py`.
**How to avoid:** Define fountain-specific constants explicitly in fountain tests: `FOUNTAIN_BYTES_PER_FRAME = 4050`, `FOUNTAIN_HEADER_LEN = 6`, `FOUNTAIN_PAYLOAD_SIZE = 4044`.
**Warning signs:** Data length mismatches, XOR corruption in fountain decode.

### Pitfall 3: sys.stdout.write Side Effect in encode_frame
**What goes wrong:** `encode_frame()` writes progress output to stdout (`sys.stdout.write(f"\rProgress...")`). This pollutes test output and slows down tests with many frames.
**Why it happens:** Progress display is embedded in the encoding function with no option to disable it.
**How to avoid:** Accept the noise in test output -- do NOT modify production code in this phase. Optionally capture stdout in tests using `capsys` fixture if the output is distracting.
**Warning signs:** Progress percentages appearing in test output.

### Pitfall 4: Import Path Issues
**What goes wrong:** `from sender import encode_frame` fails with `ModuleNotFoundError` when running pytest from a different directory.
**Why it happens:** The project has no `__init__.py`, no `setup.py`/`pyproject.toml`, and modules are at the project root.
**How to avoid:** Add `sys.path.insert(0, project_root)` in `conftest.py`. Alternatively, always run `pytest` from the project root.
**Warning signs:** `ModuleNotFoundError: No module named 'sender'`.

### Pitfall 5: CAP_DSHOW in Loopback Tests on Linux
**What goes wrong:** Both `receiver.py` and `receiver_fountain.py` hardcode `cv2.CAP_DSHOW` which is Windows DirectShow. On Linux this constant may not exist or may cause silent failure.
**Why it happens:** Original code was developed on Windows.
**How to avoid:** Loopback tests should use platform-appropriate capture backend, or use `cv2.CAP_ANY` (0) for auto-detection. This is a known issue documented in CONCERNS.md. For Phase 1, the loopback test should detect the platform and use the correct backend. OR, since loopback tests are hardware-optional and behind `--hardware`, document that they may need adjustment per platform.
**Warning signs:** `cap.isOpened()` returns `False` on Linux.

### Pitfall 6: Fountain Decoder Overhead Variability
**What goes wrong:** Fountain decoding requires more droplets than K (the number of source chunks) due to the probabilistic nature of LT codes. Tests with tight assertions on "exactly K droplets needed" will fail intermittently.
**Why it happens:** Degree distribution is random; some seeds produce redundant droplets.
**How to avoid:** Allow overhead in tests. Send up to `K * 5` or `K * 10` droplets and assert completion within that budget. For small K (1-3 chunks), overhead is usually 1.0x-1.5x. For larger K, budget 2x-3x.
**Warning signs:** Test passes sometimes but fails on other runs.

## Code Examples

Verified patterns from direct codebase analysis:

### Sequential Encode/Decode Round-Trip (Verified Working)
```python
# Source: Direct testing on this system (2026-02-16)
from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import BYTES_PER_FRAME

# Correct function signatures:
data = b'\x42' * BYTES_PER_FRAME
frame = encode_frame(data, 0, 1)          # (data_chunk, frame_index, total_frames)
sampled = sample_frame(frame)              # (frame) -> grid
idx, total, decoded, length = decode_frame(sampled)  # returns 4 values
assert decoded == data
```

### Fountain Encode/Decode Round-Trip (Verified Working)
```python
# Source: Direct testing on this system (2026-02-16)
from receiver_fountain import PRNG, FountainDecoder

PAYLOAD_SIZE = 4044

def choose_indices(seed, K):
    prng = PRNG(seed)
    degree = 1
    r = prng.next_float()
    if r < 0.1: degree = 1
    elif r < 0.6: degree = 2
    else: degree = int(prng.next_float() * min(K, 20)) + 1
    indices = set()
    while len(indices) < degree:
        indices.add(prng.next() % K)
    return indices

def build_droplet(seed, K, chunks):
    indices = choose_indices(seed, K)
    payload = bytearray(PAYLOAD_SIZE)
    for idx in indices:
        for i in range(PAYLOAD_SIZE):
            payload[i] ^= chunks[idx][i]
    return payload

# Usage:
test_data = os.urandom(10000)
K = -(-len(test_data) // PAYLOAD_SIZE)  # ceil division
chunks = []
for i in range(K):
    chunk = bytearray(PAYLOAD_SIZE)
    start = i * PAYLOAD_SIZE
    end = min(start + PAYLOAD_SIZE, len(test_data))
    chunk[:end-start] = test_data[start:end]
    chunks.append(chunk)

decoder = FountainDecoder(K, PAYLOAD_SIZE)
seed = 1
while not decoder.is_complete() and seed < K * 10:
    payload = build_droplet(seed, K, chunks)
    decoder.add_droplet(seed, payload)
    seed += 1

assert decoder.is_complete()
recovered = decoder.get_file_data()[:len(test_data)]
assert recovered == bytearray(test_data)
```

### PRNG Cross-Language Verification (Verified Matching)
```python
# Source: Direct comparison on this system (2026-02-16)
# Python outputs for seed=1: [1580013426, 350525680, 3524174333, 3011703609, 643872864]
# JS outputs for seed=1:     [1580013426, 350525680, 3524174333, 3011703609, 643872864]
# IDENTICAL for all tested seeds: 1, 42, 1000, 0xDEADBEEF

from receiver_fountain import PRNG

def test_prng_known_vectors():
    vectors = {
        1: [1580013426, 350525680, 3524174333, 3011703609, 643872864],
        42: [551831576, 144025891, 322543647, 3034809370, 908029994],
        1000: [906530639, 1890395030, 856335010, 2112903289, 3199101553],
        0xDEADBEEF: [46217145, 304148291, 1711218402, 2692075039, 4098511199],
    }
    for seed, expected in vectors.items():
        prng = PRNG(seed)
        for val in expected:
            assert prng.next() == val, f"Mismatch at seed={seed}"
```

### Hypothesis Property-Based Test Pattern
```python
# Source: hypothesis documentation + codebase analysis
from hypothesis import given, settings
from hypothesis.strategies import binary
from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import BYTES_PER_FRAME

@given(data=binary(min_size=1, max_size=BYTES_PER_FRAME))
@settings(max_examples=200, deadline=None)
def test_sequential_roundtrip_property(data):
    """Any binary data that fits in a frame should survive encode/decode."""
    frame = encode_frame(data, 0, 1)
    sampled = sample_frame(frame)
    idx, total, decoded, length = decode_frame(sampled)
    assert idx == 0
    assert total == 1
    assert length == len(data)
    assert decoded == data
```

### pytest.ini Configuration
```ini
[pytest]
testpaths = tests
addopts = --strict-markers -v
markers =
    hardware: marks tests requiring Elgato capture card (deselect with '-m "not hardware"')
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `test_loopback.py` as standalone script (`if __name__ == "__main__"`) | pytest-discoverable test functions (`test_*`) | This phase | Tests run with `pytest` instead of manual execution |
| No property-based testing | hypothesis with `binary()` strategy | This phase | Catches edge cases in encode/decode that fixed examples miss |
| No PRNG verification | Static JSON vectors from authoritative JS source | This phase | Guarantees Python/JS PRNG synchronization before fountain code changes |
| Hardware tests always run or always skipped | `@pytest.mark.hardware` with `--hardware` opt-in | This phase | Tests useful with or without Elgato connected |

**Deprecated/outdated:**
- The existing `test_loopback.py` is broken and must be fixed (wrong function signatures)
- Running tests via `python tests/test_loopback.py` directly -- use `pytest` instead

## Codebase-Specific Findings

### Confirmed Function Signatures (HIGH confidence -- directly tested)

| Function | Module | Signature | Returns |
|----------|--------|-----------|---------|
| `encode_frame` | sender.py | `(data_chunk, frame_index, total_frames)` | `numpy.ndarray` (H, W, 3) |
| `sample_frame` | receiver.py | `(frame)` | `numpy.ndarray` (ROWS, COLS, 3) |
| `decode_frame` | receiver.py | `(frame_grid)` | `(frame_index, total_frames, data, data_len)` or `(None, None, None, None)` |
| `sample_frame` | receiver_fountain.py | `(frame, offset_x=0, offset_y=0, scale_x=1.0, scale_y=1.0)` | `numpy.ndarray` |
| `decode_frame_data` | receiver_fountain.py | `(sampled_grid)` | `bytes` |
| `PRNG.__init__` | receiver_fountain.py | `(seed)` | -- |
| `PRNG.next` | receiver_fountain.py | `()` | `int` (uint32) |
| `PRNG.next_float` | receiver_fountain.py | `()` | `float` [0, 1) |
| `FountainDecoder.__init__` | receiver_fountain.py | `(total_chunks, payload_size)` | -- |
| `FountainDecoder.add_droplet` | receiver_fountain.py | `(seed, data)` | `None` |
| `FountainDecoder.is_complete` | receiver_fountain.py | `()` | `bool` |
| `FountainDecoder.get_file_data` | receiver_fountain.py | `()` | `bytearray` |

### Confirmed Constants

| Constant | Value | Source | Used By |
|----------|-------|--------|---------|
| WIDTH | 1920 | common.py | Both modes |
| HEIGHT | 1080 | common.py | Both modes |
| BLOCK_SIZE | 8 | common.py | Both modes |
| ROWS | 135 | common.py | Both modes |
| COLS | 240 | common.py | Both modes |
| BLOCKS_PER_FRAME | 32400 | common.py | Both modes |
| HEADER_SIZE | 12 | common.py | Sequential only |
| BYTES_PER_FRAME | 12138 | common.py | Sequential only |
| FOUNTAIN_BYTES_PER_FRAME | 4050 | sender.html / receiver_fountain.py (local) | Fountain only |
| FOUNTAIN_HEADER_LEN | 6 | sender.html / receiver_fountain.py (local) | Fountain only |
| FOUNTAIN_PAYLOAD_SIZE | 4044 | sender.html / receiver_fountain.py (local) | Fountain only |

### PRNG Analysis (HIGH confidence -- directly verified)
- Python `(self.a | 0)` is a confirmed no-op. Safe to remove but NOT in this phase (no production code changes).
- Python and JS SplitMix32 produce identical outputs for seeds: 0, 1, 42, 1000, 0xFFFFFFFF, 0xDEADBEEF.
- `chooseIndices()` produces identical degree and index sets across Python and JS for seeds 1-20 with K=10.
- Node.js v20.19.5 is available on this system for vector generation.

## Open Questions

Things that couldn't be fully resolved:

1. **Elgato capture card availability on this Linux machine**
   - What we know: The code uses `cv2.CAP_DSHOW` which is Windows-only. The user works on both Windows and Linux.
   - What's unclear: Whether the Elgato is currently connected to this Linux machine, and what device path it would be (`/dev/video0`?).
   - Recommendation: Loopback test should auto-detect platform for capture backend. Mark as `@pytest.mark.hardware`. The loopback test should gracefully skip if no capture device is found (not just if `--hardware` flag is missing).

2. **Optimal number of PRNG test vectors**
   - What we know: Context says "1000+ seeds". Direct comparison confirmed exact match for 6 seeds. chooseIndices confirmed for 20 seeds.
   - What's unclear: Whether 1000 is sufficient or overkill given the algorithm is deterministic.
   - Recommendation: Generate 1024 seeds (powers-of-2 friendly), 10 outputs each. Also include edge cases: seed=0, seed=0xFFFFFFFF, seed=1. Additionally verify `chooseIndices` for 50+ seeds with multiple K values.

3. **Multi-frame sequential tests**
   - What we know: Single-frame round-trip works. Multi-frame requires concatenation logic.
   - What's unclear: Whether the metadata wrapping (filename prepend) should be tested in this phase or deferred.
   - Recommendation: Test multi-frame data assembly (split data, encode each frame, decode each, reassemble, compare). Metadata wrapping is an integration concern -- test it if time permits but it's not core to encode/decode correctness.

## Sources

### Primary (HIGH confidence)
- **Direct codebase analysis** -- All source files read and function signatures verified by execution
- **Direct PRNG comparison** -- Python and JS outputs compared on this system with Node.js v20.19.5
- **Direct round-trip verification** -- Both sequential and fountain encode/decode confirmed working in memory

### Secondary (MEDIUM confidence)
- [pytest custom markers documentation](https://docs.pytest.org/en/stable/example/markers.html) -- marker registration, `--strict-markers`
- [pytest skip/xfail documentation](https://docs.pytest.org/en/stable/how-to/skipping.html) -- conditional skip patterns
- [hypothesis documentation](https://hypothesis.readthedocs.io/) -- `binary()` strategy, `@given`, `@settings`
- [hypothesis strategies reference](https://hypothesis.readthedocs.io/en/latest/data.html) -- data generation strategies

### Tertiary (LOW confidence)
- None -- all findings verified through direct execution or official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified installed and working on this system
- Architecture: HIGH -- test patterns verified by executing actual encode/decode round-trips
- Pitfalls: HIGH -- bugs confirmed by reading source code; signatures verified by execution
- PRNG analysis: HIGH -- cross-language comparison executed directly with matching results

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (stable domain, no rapidly changing dependencies)
