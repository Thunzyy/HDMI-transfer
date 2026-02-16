# Stack Research

**Domain:** HDMI data exfiltration via capture card -- maximizing throughput
**Researched:** 2026-02-16
**Confidence:** MEDIUM-HIGH (core stack verified, some capture-path specifics are hardware-dependent)

## Current State

The prototype uses Python 3.13, OpenCV (cv2.imshow for sender display, cv2.VideoCapture for receiver capture), NumPy for bit packing, and a hand-rolled LT fountain code decoder. The sender is Windows-only (ctypes.windll). The browser sender uses vanilla JS with Canvas + requestAnimationFrame.

**Current throughput bottlenecks identified from code review:**
1. `cv2.imshow` + `cv2.waitKey(delay)` -- caps sender FPS, not designed for high-perf rendering
2. `cv2.VideoCapture` with `CAP_DSHOW` -- Windows-only, blocking reads, not optimized for 240fps UVC
3. 3-bit encoding (1 bit per R/G/B channel) -- theoretically ~12KB/frame at 1080p with 8x8 blocks, but fragile
4. Fountain decoder uses Python `bytearray` XOR loops -- O(n) per symbol in pure Python
5. No async/threaded pipeline -- encode, display, capture, decode all serial

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Python | 3.13+ | Runtime | Already in use; free-threading (PEP 703) experimental support is a bonus for future pipeline parallelism | HIGH |
| NumPy | >=2.4.2 | Array operations, bit pack/unpack, XOR | Already in use. `np.packbits`/`np.unpackbits` are the fastest pure-Python bit packing. Vectorized XOR via `np.bitwise_xor` is critical for fountain code performance. Latest 2.4.x has improved free-threaded support. | HIGH |
| OpenCV (opencv-python-headless) | >=4.10 | Receiver: frame capture from capture card | Keep for capture -- it wraps V4L2 (Linux) / DirectShow (Windows) well. Use `CAP_V4L2` backend on Linux for best performance. Switch to `opencv-python-headless` to avoid GUI dependency conflicts with the sender display library. | HIGH |
| Numba | >=0.61 | JIT-compile fountain encode/decode hot loops | `@njit` turns Python XOR loops into SIMD-vectorized machine code with zero boilerplate. 100-1000x speedup over pure Python for the fountain encoder's XOR-across-chunks operation. `@njit(parallel=True)` with `prange` for encoding multiple symbols simultaneously. | HIGH |
| pygame-ce | >=2.5.6 | Sender: fullscreen frame display | SDL2-backed, hardware-accelerated blitting. `pygame.surfarray.blit_array()` renders a NumPy array directly to a fullscreen surface with zero copy. Faster than `cv2.imshow` which uses platform-specific windowing (Win32 DIB) not designed for high-throughput rendering. pygame-ce is the actively maintained fork (original pygame has stalled). | MEDIUM-HIGH |

### Supporting Libraries

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| bitarray | >=3.8.0 | Advanced bit-level manipulation | When you need bit-level indexing, variable-length prefix codes, or efficient boolean arrays beyond what `np.packbits` provides. C-implemented, 60x faster than dict-based alternatives. Interoperates with NumPy via `.pack()`/`.unpack()`. | MEDIUM |
| hypothesis | >=6.100 | Property-based testing for encode/decode round-trips | Testing that `decode(encode(data)) == data` for arbitrary binary inputs. `st.binary()` strategy generates edge-case binary data automatically. Integrates natively with pytest. | HIGH |
| pytest | >=8.0 | Test framework | Standard Python testing. Fixtures for hardware mocking (mock `cv2.VideoCapture`), markers for skipping hardware-dependent tests in CI. | HIGH |
| pytest-cov | >=5.0 | Coverage reporting | Measuring test coverage of encode/decode paths | HIGH |
| ruff | >=0.9 | Linter + formatter (replaces flake8+black+isort) | Single Rust-based tool, 100x faster than flake8. Configure in `pyproject.toml`. | HIGH |
| mypy | >=1.14 | Static type checking | Type-check the encode/decode pipeline. NumPy stubs are mature in 2025+. | HIGH |
| v4l2py | >=3.1 | Direct V4L2 access on Linux | If OpenCV's V4L2 backend doesn't achieve 240fps, bypass it with direct V4L2 mmap capture for zero-copy frame access. Async support (asyncio/gevent). Only needed if OpenCV capture is the bottleneck. | LOW-MEDIUM |
| structlog | >=25.1 | Structured logging | Replace `print()` statements with structured, leveled logging for production debugging of transfer sessions. | MEDIUM |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pyproject.toml | Unified project config | Single file for build, deps, ruff, pytest, mypy config. Use `hatchling` as build backend. |
| uv | Package manager | Rust-based, 10-100x faster than pip. Use `uv pip install` and `uv venv`. |
| pre-commit | Git hooks | Run ruff + mypy + pytest before each commit |

## Installation

```bash
# Create virtual environment
uv venv .venv && source .venv/bin/activate

# Core dependencies
uv pip install numpy>=2.4.2 opencv-python-headless>=4.10 pygame-ce>=2.5.6 numba>=0.61

# Supporting
uv pip install bitarray>=3.8.0 structlog>=25.1

# Dev dependencies
uv pip install pytest>=8.0 pytest-cov>=5.0 hypothesis>=6.100 ruff>=0.9 mypy>=1.14 pre-commit
```

## Detailed Rationale

### Sender Display: pygame-ce over cv2.imshow

**Problem:** `cv2.imshow` is a debugging tool, not a rendering engine. On Windows it creates a Win32 window, copies the `cv::Mat` into a DIB bitmap, and invalidates the window rect. On Linux it uses GTK or Qt. Both paths have unnecessary overhead for our use case (rendering a pre-computed NumPy array fullscreen at max FPS).

**Solution:** pygame-ce with SDL2 backend.

```python
import pygame
import numpy as np

pygame.init()
screen = pygame.display.set_mode((1920, 1080), pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
pygame.display.set_caption("HDMI Exfil Sender")

# Render a frame (NumPy array -> screen)
frame = np.zeros((1080, 1920, 3), dtype=np.uint8)  # your encoded frame
pygame.surfarray.blit_array(screen, frame.transpose(1, 0, 2))  # pygame wants (W, H, 3)
pygame.display.flip()
```

**Why not ModernGL/OpenGL?** ModernGL (v5.12.0) with PBO double-buffering is theoretically fastest for GPU texture upload. However, it adds significant complexity (shader programs, texture management, OpenGL context) for marginal gain. Our frames are pre-computed NumPy arrays -- the bottleneck is RAM-to-VRAM transfer, which SDL2's `blit_array` handles efficiently via hardware-accelerated blitting. ModernGL is overkill unless we hit a display bottleneck, which is unlikely at 1080p.

**Why not DXcam/BetterCam for display?** DXcam captures screens; it does not render to them. It uses Desktop Duplication API for screen capture (input), not display (output). Wrong tool.

### Receiver Capture: OpenCV CAP_V4L2 (Linux) / CAP_DSHOW (Windows)

**Problem:** Current code hardcodes `cv2.CAP_DSHOW` (Windows only). Need cross-platform, high-FPS capture.

**Solution:** Use OpenCV with platform-appropriate backend:

```python
import cv2
import platform

if platform.system() == "Linux":
    cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
    # MJPG codec for higher FPS (less bandwidth than raw YUYV)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
elif platform.system() == "Windows":
    cap = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cap.set(cv2.CAP_PROP_FPS, 240)
```

**Elgato 4K X at 1080p240:**
- Capture formats: **NV12** (4:2:0, SDR) or **YUY2/YUYV** (4:2:2, SDR)
- For data exfil, NV12 is fine -- we only need luminance channel for black/white block decoding
- 4:4:4 RGB capture maxes at **1080p120** -- not 240fps
- On Linux: UVC/V4L2 driver. May need `uvcvideo quirks=0x80` for bandwidth issues

**Fallback:** If OpenCV V4L2 cannot sustain 240fps, use `v4l2py` with mmap for zero-copy frames, or `ffmpegcv` which provides GPU-accelerated decode. These are escalation paths, not defaults.

**Why not GStreamer?** Viable but adds pipeline complexity. OpenCV can use GStreamer as a backend (`CAP_GSTREAMER`) if needed, so this is a configuration change, not a library swap.

### Fountain Codes: Custom (Numba-accelerated) over External Libraries

**Problem:** External LT code libraries (`lt-code` on PyPI, `Spriteware/lt-codes-python`) are:
1. Not optimized for real-time streaming (designed for file transfer)
2. Use pure Python XOR loops (slow)
3. Don't match the existing PRNG/degree distribution in the codebase
4. Would require rewriting the browser sender's JS implementation to match

**Solution:** Keep custom fountain code, but accelerate with Numba.

```python
import numba
import numpy as np

@numba.njit
def xor_chunks(target: np.ndarray, source: np.ndarray) -> None:
    """XOR source into target in-place. SIMD-vectorized by Numba."""
    for i in range(len(target)):
        target[i] ^= source[i]

@numba.njit(parallel=True)
def encode_symbols(source_chunks: np.ndarray, seeds: np.ndarray, K: int) -> np.ndarray:
    """Encode multiple fountain symbols in parallel."""
    n_symbols = len(seeds)
    symbol_size = source_chunks.shape[1]
    output = np.zeros((n_symbols, symbol_size), dtype=np.uint8)
    for s in numba.prange(n_symbols):
        # ... degree distribution + XOR logic with PRNG
        pass
    return output
```

**Why not Raptor codes (RFC 6330)?** Raptor codes have linear-time encode/decode (vs LT's O(K*ln(K))) and near-optimal overhead. However:
1. Patented (Qualcomm) -- legal risk for open-source
2. No maintained Python implementation exists
3. The only open-source implementation (OpenRQ) is Java
4. LT codes are sufficient for our channel (HDMI is low-loss; the main issue is frame drops, not bit errors)

**Why not `lt-code` from PyPI?** Its belief-propagation decoder and degree distribution differ from the existing codebase's SplitMix32 PRNG + custom distribution. Adopting it would break compatibility with the browser sender.

### Bit Encoding: NumPy vectorized (current) is optimal

**Current approach:** `np.unpackbits` / `np.packbits` with threshold at 128. This is already near-optimal.

**Potential improvement -- multi-bit encoding:**
Instead of 1 bit per channel (black/white), use 2 bits per channel (4 levels: 0, 85, 170, 255). This doubles throughput from 3 bits/block to 6 bits/block.

```python
# 2-bit encoding: 4 levels per channel
LEVELS = np.array([0, 85, 170, 255], dtype=np.uint8)

# Encode: 2 bits -> level
def encode_2bit(bits_pair):
    return LEVELS[bits_pair[0] * 2 + bits_pair[1]]

# Decode: level -> 2 bits (with threshold ranges)
THRESHOLDS = np.array([42, 127, 212], dtype=np.uint8)
```

This is an architecture decision, not a library choice. The stack supports it via NumPy's vectorized operations.

### Testing: pytest + hypothesis + hardware mocking

**Strategy:**
1. **Unit tests** (no hardware): Encode/decode round-trips, fountain code algebra, bit packing
2. **Property-based tests** (Hypothesis): `decode(encode(arbitrary_binary)) == arbitrary_binary`
3. **Integration tests** (hardware-optional): Capture card tests with `pytest.mark.skipif` when no device

```python
# conftest.py
import pytest

@pytest.fixture
def mock_capture(monkeypatch):
    """Mock cv2.VideoCapture for CI environments."""
    class FakeCapture:
        def __init__(self, *args, **kwargs): pass
        def isOpened(self): return True
        def read(self):
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            return True, frame
        def set(self, prop, val): return True
        def release(self): pass
    monkeypatch.setattr("cv2.VideoCapture", FakeCapture)

# test_roundtrip.py
from hypothesis import given, strategies as st

@given(data=st.binary(min_size=1, max_size=50000))
def test_encode_decode_roundtrip(data):
    frames = encode_to_frames(data)
    recovered = decode_from_frames(frames)
    assert recovered == data
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| pygame-ce (SDL2) | ModernGL 5.12.0 + glfw 2.10.0 | If pygame's `blit_array` becomes a bottleneck. ModernGL + PBO double-buffering is the fastest GPU texture upload path. Adds ~200 lines of boilerplate (shader, texture, PBO management). |
| pygame-ce (SDL2) | cv2.imshow (current) | Never for production. Only for quick debugging. |
| OpenCV CAP_V4L2 | v4l2py 3.1+ | If OpenCV cannot sustain 240fps on Linux. v4l2py uses mmap for zero-copy frames. More complex API. |
| OpenCV CAP_V4L2 | ffmpegcv | If you need GPU-accelerated decode (NVIDIA). Drop-in replacement for cv2.VideoCapture API. |
| Custom LT codes + Numba | lt-code (PyPI) | If starting from scratch with no browser sender to maintain. Provides a clean stream API. |
| Custom LT codes + Numba | RaptorQ (RFC 6330) | If patent concerns are resolved and a Python binding exists. ~0.5% overhead vs LT's ~5-10%. |
| Numba @njit | Cython | If Numba's JIT warmup time is unacceptable (first call compiles). Cython AOT-compiles but requires .pyx files and a build step. |
| NumPy bit ops | bitarray 3.8.0 | If you need variable-length prefix codes or bit-level indexing beyond pack/unpack. For standard pack/unpack, NumPy is faster and already a dependency. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| DXcam / BetterCam | Screen capture library (Desktop Duplication API). Captures what's on screen. Does NOT interface with USB capture cards. Wrong tool for receiver. | OpenCV CAP_V4L2 / CAP_DSHOW for capture card input |
| PyQt / Tkinter for sender display | Heavyweight GUI frameworks with event loops not designed for 240fps rendering | pygame-ce with SDL2 |
| Original `pygame` (not `-ce`) | Development stalled; single-maintainer governance; slower to get bug fixes | `pygame-ce` (Community Edition) |
| `setup.py` / `setup.cfg` | Legacy packaging. PEP 621 standardized `pyproject.toml` | `pyproject.toml` with hatchling backend |
| `black` + `flake8` + `isort` (separately) | Three tools to install, configure, and keep in sync | `ruff` (single tool, 100x faster, configurable in pyproject.toml) |
| Pure Python XOR loops | O(n) per symbol in CPython interpreter. With 4KB symbols and 1000 chunks, this is the throughput bottleneck | Numba `@njit` or NumPy vectorized `np.bitwise_xor` |
| `pip` | Slow resolver, no lockfiles | `uv` (Rust-based, 10-100x faster) |
| `cv2.CAP_DSHOW` on Linux | DirectShow is Windows-only. Code will crash on Linux. | `cv2.CAP_V4L2` on Linux, `cv2.CAP_DSHOW` on Windows (platform-detect) |

## Stack Patterns by Variant

**If sender runs on Windows (primary use case):**
- Use pygame-ce with SDL2 backend (works on Windows)
- ctypes.windll for monitor detection (already implemented)
- OpenCV with CAP_DSHOW for any Windows-side capture testing

**If sender runs on Linux:**
- Use pygame-ce with SDL2 backend (works on Linux)
- Use `xrandr` or `pygame.display.get_desktop_sizes()` for monitor detection
- Replace ctypes.windll monitor detection with cross-platform alternative

**If receiver runs on Linux (likely -- your dev machine is Kali Linux):**
- OpenCV with CAP_V4L2 backend
- Set MJPG fourcc for bandwidth efficiency at 240fps
- May need `uvcvideo` kernel module options for Elgato: `modprobe uvcvideo quirks=0x80`
- Fallback: v4l2py with mmap if OpenCV can't sustain frame rate

**If targeting max throughput (research path):**
- 2-bit-per-channel encoding (4 levels) doubles payload vs 1-bit (binary)
- Smaller block size (4x4 instead of 8x8) quadruples blocks but needs cleaner signal
- BLOCK_SIZE and LEVELS should be configurable, not hardcoded
- Pre-compute all frames into a ring buffer before transmission starts

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| numba >=0.61 | numpy >=2.1, <2.5 | Numba pins NumPy upper bound. Check `numba.np.numpy_support` for dtype support. |
| pygame-ce >=2.5.6 | Python 3.9-3.13 | SDL2 bundled. Incompatible with `pygame` (cannot install both). |
| opencv-python-headless >=4.10 | numpy >=2.0 | Use `-headless` to avoid GUI backend conflicts with pygame-ce. |
| hypothesis >=6.100 | pytest >=8.0 | Native integration, no adapter needed. |
| ruff >=0.9 | pyproject.toml | Configure via `[tool.ruff]` section. |
| mypy >=1.14 | Python 3.13 | Full 3.13 support including PEP 695 type aliases. |

## Throughput Projections

Based on the Elgato 4K X specifications and encoding parameters:

| Config | Bits/Frame | Bytes/Frame | @ 60fps | @ 120fps | @ 240fps |
|--------|-----------|-------------|---------|----------|----------|
| 8x8 blocks, 1-bit/channel (current) | 32,400 * 3 = 97,200 | ~12 KB | ~720 KB/s (5.6 Mbps) | ~1.4 MB/s (11.2 Mbps) | ~2.8 MB/s (22.5 Mbps) |
| 8x8 blocks, 2-bit/channel | 32,400 * 6 = 194,400 | ~24 KB | ~1.4 MB/s | ~2.8 MB/s | ~5.7 MB/s (45 Mbps) |
| 4x4 blocks, 1-bit/channel | 129,600 * 3 = 388,800 | ~48 KB | ~2.8 MB/s | ~5.7 MB/s | ~11.4 MB/s (90 Mbps) |
| 4x4 blocks, 2-bit/channel | 129,600 * 6 = 777,600 | ~97 KB | ~5.7 MB/s | ~11.4 MB/s | ~22.8 MB/s (180 Mbps) |

Note: Fountain code overhead adds ~5-15% redundancy. Actual throughput will be lower due to frame drops, capture latency, and decode time. The 240fps capture on the Elgato 4K X uses NV12 (4:2:0 chroma subsampling) which affects color channel fidelity -- may limit multi-bit-per-channel encoding reliability.

## Sources

- [Elgato 4K X Supported Resolutions](https://help.elgato.com/hc/en-us/articles/23479175821069) -- 1080p240 NV12/YUY2 capture confirmed (MEDIUM confidence, specs page was 403 but multiple secondary sources agree)
- [Elgato 4K X Linux CLI tool](https://github.com/13bm/elgato4k-linux) -- Linux V4L2/UVC support status
- [DXcam GitHub](https://github.com/ra1nty/DXcam) -- confirmed this is screen capture only, not capture card input
- [pygame-ce PyPI](https://pypi.org/project/pygame-ce/) -- v2.5.6, Oct 2025
- [pygame-ce Performance Wiki](https://github.com/pygame-community/pygame-ce/wiki/Performance-Comparisons-Against-Upstream-Pygame) -- perf improvements over upstream
- [ModernGL PyPI](https://pypi.org/project/moderngl/) -- v5.12.0, texture.write() API
- [ModernGL Texture Docs](https://moderngl.readthedocs.io/en/latest/reference/texture.html) -- NumPy buffer protocol support
- [NumPy 2.4.2 PyPI](https://pypi.org/project/numpy/) -- latest stable, Jan 2026
- [numpy.packbits docs](https://numpy.org/doc/stable/reference/generated/numpy.packbits.html) -- bit packing API
- [bitarray GitHub](https://github.com/ilanschnell/bitarray) -- v3.8.0, C-implemented
- [Numba performance tips](https://numba.readthedocs.io/en/stable/user/performance-tips.html) -- @njit, parallel, SIMD
- [Spriteware/lt-codes-python](https://github.com/Spriteware/lt-codes-python) -- LT codes reference implementation
- [lt-code PyPI](https://pypi.org/project/lt-code/) -- alternative LT library
- [Raptor codes Wikipedia](https://en.wikipedia.org/wiki/Raptor_code) -- patent concerns noted
- [v4l2py GitHub](https://github.com/tiagocoutinho/v4l2py) -- direct V4L2 Python binding
- [PyV4L2Cam GitHub](https://github.com/okawo80085/PyV4L2Cam) -- high FPS V4L2
- [opencv_v4l2 GitHub](https://github.com/econsystems/opencv_v4l2) -- high FPS OpenCV V4L2 helper
- [Hypothesis docs](https://hypothesis.readthedocs.io/) -- property-based testing
- [ruff PyPI](https://pypi.org/project/ruff/) -- linter/formatter
- [pyproject.toml guide](https://pydevtools.com/handbook/reference/pyproject/) -- modern Python project config

---
*Stack research for: HDMI data exfiltration via capture card*
*Researched: 2026-02-16*
