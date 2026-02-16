# Phase 4: Performance Optimization - Research

**Researched:** 2026-02-16
**Domain:** High-throughput rendering, JIT compilation, threaded capture, binary encoding
**Confidence:** HIGH (core libraries verified via official docs; architecture patterns from codebase analysis)

## Summary

Phase 4 targets six performance requirements that together unlock maximum HDMI throughput. The current bottlenecks are:

1. **Data capacity**: Fountain mode uses 1 bit per block (4,038 bytes/frame) while sequential already uses 3 bits per block (12,133 bytes/frame). Upgrading fountain to 3bpp triples per-frame capacity to 12,138 bytes/frame.
2. **Display FPS**: `cv2.imshow` + `cv2.waitKey(1)` has a hard floor of ~12-13ms per call due to OS timer resolution, capping display at ~70-80 FPS regardless of hardware. pygame-ce with SDL2 vsync bypasses this entirely, rendering at the monitor's native refresh rate.
3. **XOR hot path**: The FountainDecoder's peeling loops (`add_droplet`, `resolve_chunk`) and the sender's droplet-building loop use pure Python byte-by-byte XOR (`for i in range(len(data)): data[i] ^= chunk[i]`). With 3bpp payloads of 12,138 bytes and ~200 droplets per transfer, this is millions of Python-interpreted XOR operations -- a textbook Numba @njit target.
4. **Capture pipeline**: `cap.read()` is blocking -- the main thread stalls while the USB/HDMI capture card delivers the next frame. A dedicated capture thread with a ring buffer eliminates this stall.

**Primary recommendation:** Implement all six requirements as independent modules that slot into the existing architecture. The 3bpp upgrade changes `FountainProtocol` encode/decode. The pygame-ce renderer replaces `FrameRenderer`. Numba accelerates standalone XOR functions. The threaded capture wraps `CaptureSource`. No architectural changes needed -- each optimization is additive.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pygame-ce | >= 2.5.6 | SDL2 fullscreen rendering at native refresh rate | Only Python SDL2 binding that supports vsync + fullscreen + numpy surface blitting. Replaces cv2.imshow ceiling of ~80fps |
| numba | >= 0.61.0 | JIT-compile XOR hot loops to machine code | @njit on byte-by-byte XOR loops achieves 100x+ speedup over pure Python. Supports Python 3.11-3.14, NumPy 1.24+ |
| opencv-python-headless | >= 4.0 | Video capture and image processing (no GUI) | Headless variant avoids display library conflicts with pygame-ce. Still provides VideoCapture, resize, etc. |
| numpy | >= 1.24 | Array operations (existing dependency) | Already used throughout; Numba requires it |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| threading (stdlib) | N/A | Dedicated capture thread | Wrap CaptureSource.read() in background thread |
| collections.deque (stdlib) | N/A | Ring buffer for captured frames | maxlen-bounded deque; append/popleft are thread-safe in CPython |
| time.perf_counter_ns (stdlib) | N/A | High-precision FPS measurement | Nanosecond precision, monotonic, no float drift |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pygame-ce | pyglet | pyglet has OpenGL rendering but less mature numpy/surface integration; pygame-ce has proven surfarray pipeline |
| pygame-ce | raw SDL2 via ctypes | Maximum control but massive boilerplate; pygame-ce wraps it cleanly |
| numba @njit | Cython | Cython requires compilation step and .pyx files; Numba is decorator-only, no build changes |
| numba @njit | numpy vectorized XOR (`a ^= b`) | NumPy vectorized XOR works BUT requires converting bytearray to numpy first AND doesn't help with the peeling decoder's variable-length operations |
| collections.deque | queue.Queue | Queue has blocking get/put which adds overhead; deque with maxlen auto-discards old frames (exactly what we want) |

### Installation
```bash
pip uninstall pygame opencv-python  # remove conflicting packages
pip install pygame-ce>=2.5.6 numba>=0.61.0 opencv-python-headless>=4.0
```

**CRITICAL**: `pygame-ce` and `pygame` share the `import pygame` namespace -- they CANNOT coexist. `opencv-python` and `opencv-python-headless` share `import cv2` -- only one can be installed. The headless variant is required when pygame-ce handles display.

## Architecture Patterns

### Recommended Module Changes
```
src/hdmi_exfil/
├── display/
│   ├── renderer.py       # MODIFY: Add PygameRenderer alongside existing FrameRenderer
│   └── monitors.py       # unchanged
├── capture/
│   ├── source.py          # unchanged (CaptureSource stays as-is)
│   ├── sampler.py         # unchanged
│   └── threaded.py        # NEW: ThreadedCapture wrapping CaptureSource
├── protocols/
│   ├── fountain.py        # MODIFY: Add 3bpp encode/decode path, Numba-accelerated XOR
│   └── xor_ops.py         # NEW: Standalone @njit XOR functions
├── cli/
│   ├── send.py            # MODIFY: Use PygameRenderer, call numba XOR in fountain loop
│   └── receive.py         # MODIFY: Use ThreadedCapture, FPS measurement
└── config.py              # unchanged
```

### Pattern 1: Pygame SDL2 Renderer (replaces cv2.imshow)
**What:** New `PygameRenderer` class implementing the same context-manager interface as `FrameRenderer` but using pygame-ce SDL2 for vsync-locked rendering.
**When to use:** Sender-side display. The receiver still needs cv2 for its debug window (which is low-priority).

```python
# Source: pygame-ce official docs (https://pyga.me/docs/ref/display.html)
import pygame
import numpy as np

class PygameRenderer:
    def __init__(self, width=1920, height=1080, x_offset=0, y_offset=0):
        pygame.init()
        # Position window on target monitor via SDL hint
        import os
        os.environ['SDL_VIDEO_WINDOW_POS'] = f'{x_offset},{y_offset}'

        try:
            self._screen = pygame.display.set_mode(
                (width, height), pygame.FULLSCREEN | pygame.NOFRAME, vsync=1
            )
        except pygame.error:
            # Fallback: no vsync
            self._screen = pygame.display.set_mode(
                (width, height), pygame.FULLSCREEN | pygame.NOFRAME
            )

        self._width = width
        self._height = height
        self._clock = pygame.time.Clock()
        # Pre-allocate surface for blit_array (avoid per-frame allocation)
        self._frame_surface = pygame.Surface((width, height))

    def show(self, frame: np.ndarray, target_fps: int = 0) -> bool:
        """Display frame (H,W,3 uint8 numpy array). Returns False if quit requested."""
        # pygame surfarray expects (W, H, 3) -- transpose from OpenCV's (H, W, 3)
        # Also convert BGR -> RGB since pygame uses RGB
        rgb_frame = frame[:, :, ::-1]  # BGR to RGB
        transposed = np.ascontiguousarray(rgb_frame.transpose(1, 0, 2))
        pygame.surfarray.blit_array(self._frame_surface, transposed)
        self._screen.blit(self._frame_surface, (0, 0))
        pygame.display.flip()  # vsync-locked if enabled

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return False
        return True

    def destroy(self):
        pygame.quit()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.destroy()
```

**CRITICAL AXIS GOTCHA:** pygame surfarray uses (width, height, 3) axis order while numpy/OpenCV uses (height, width, 3). A `.transpose(1, 0, 2)` is mandatory. This adds ~10-15% overhead per frame. For maximum performance, generate frames directly in pygame axis order to avoid the transpose.

### Pattern 2: Numba-Accelerated XOR Functions
**What:** Standalone `@njit` functions extracted from FountainDecoder loops.
**When to use:** All XOR operations in both encoder and decoder.

```python
# Source: Numba official docs (https://numba.readthedocs.io/en/stable/user/5minguide.html)
import numpy as np
from numba import njit

@njit
def xor_into(dst: np.ndarray, src: np.ndarray) -> None:
    """XOR src into dst in-place. Both must be uint8 arrays of equal length."""
    for i in range(len(dst)):
        dst[i] ^= src[i]
```

The FountainDecoder currently does:
```python
for i in range(len(current_data)):
    current_data[i] ^= chunk_data[i]
```
Replace with: `xor_into(np.frombuffer(current_data, dtype=np.uint8), np.frombuffer(chunk_data, dtype=np.uint8))`

**Note:** `bytearray` cannot be passed directly to @njit. Convert to `np.uint8` array first. The decoder should store chunks as numpy arrays internally for maximum performance.

### Pattern 3: Threaded Capture with Ring Buffer
**What:** Background thread continuously calls `cap.read()` and stores frames in a bounded deque.
**When to use:** Receiver-side capture pipeline.

```python
# Source: PyImageSearch threaded capture pattern
import threading
from collections import deque

class ThreadedCapture:
    def __init__(self, source: CaptureSource, buffer_size: int = 64):
        self._source = source
        self._buffer = deque(maxlen=buffer_size)
        self._stopped = False
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._frame_count = 0
        self._start_time = None

    def start(self):
        self._start_time = time.perf_counter_ns()
        self._thread.start()
        return self

    def _capture_loop(self):
        while not self._stopped:
            ret, frame = self._source.read()
            if ret:
                self._buffer.append(frame)
                self._frame_count += 1

    def read(self):
        """Non-blocking read. Returns (True, frame) or (False, None)."""
        if self._buffer:
            return True, self._buffer.popleft()
        return False, None

    @property
    def actual_fps(self) -> float:
        if self._start_time is None or self._frame_count == 0:
            return 0.0
        elapsed = (time.perf_counter_ns() - self._start_time) / 1e9
        return self._frame_count / elapsed if elapsed > 0 else 0.0

    def stop(self):
        self._stopped = True
        self._thread.join(timeout=2.0)
```

### Pattern 4: 3-Bit-Per-Block Fountain Encoding
**What:** Upgrade fountain from 1bpp (black/white) to 3bpp (RGB binary), tripling capacity.
**When to use:** Fountain mode encode and decode paths.

The sequential protocol already uses 3bpp encoding (each block has 3 bits, one per R/G/B channel, each either 0 or 255). The fountain protocol currently uses 1bpp (all-white or all-black). The upgrade makes fountain use the same 3bpp encoding as sequential.

```python
# 3bpp encode: same as SequentialProtocol.encode_frame bit-packing
byte_arr = np.frombuffer(frame_bytes, dtype=np.uint8)
bits = np.unpackbits(byte_arr)
total_bits_needed = BLOCKS_PER_FRAME * 3
if len(bits) < total_bits_needed:
    bits = np.pad(bits, (0, total_bits_needed - len(bits)), 'constant')
pixel_bits = bits[:total_bits_needed].reshape((BLOCKS_PER_FRAME, 3))
pixel_values = pixel_bits * 255
blocks_grid = pixel_values.reshape((ROWS, COLS, 3)).astype(np.uint8)

# 3bpp decode: threshold all 3 channels (same as SequentialProtocol.decode_frame)
flat_pixels = sampled_grid.reshape(-1, 3)
bits = (flat_pixels > 128).astype(np.uint8)
flat_bits = bits.reshape(-1)
packed_bytes = np.packbits(flat_bits)
```

### Anti-Patterns to Avoid
- **Mixing pygame and cv2 display in the same process**: pygame-ce and OpenCV both want control of the display subsystem. Use pygame for display, cv2 only for capture/processing (headless).
- **Creating new pygame Surface every frame**: Use `blit_array` on a pre-allocated surface, never `make_surface` in the render loop.
- **Passing bytearray to Numba @njit**: Numba does not support Python `bytearray`. Always convert to `np.uint8` ndarray before calling @njit functions.
- **Putting the transpose inside the hot loop without optimization**: If generating frames from numpy, build them in pygame's (W,H,3) order from the start to avoid the transpose penalty.
- **Using `time.sleep()` for frame timing**: OS timer resolution is ~16ms on Windows. Use pygame's vsync or `Clock.tick_busy_loop()` instead.
- **Locking a Surface and blitting to it simultaneously**: `pixels3d` locks the surface -- must delete the reference before `flip()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Vsync-locked frame display | Custom OpenGL vsync loop | `pygame.display.set_mode(vsync=1)` + `flip()` | SDL2 handles all platform-specific vsync negotiation |
| XOR acceleration | Custom C extension or ctypes wrapper | `numba @njit` with `uint8` arrays | Zero build complexity, same performance, pure Python decorator |
| Ring buffer for frames | Custom circular buffer class | `collections.deque(maxlen=N)` | Thread-safe append/popleft in CPython, auto-discard oldest |
| High-precision FPS timer | Custom rdtsc wrapper | `time.perf_counter_ns()` | Nanosecond integer precision, monotonic, stdlib |
| NumPy array to pygame surface | Manual pixel-by-pixel copy | `pygame.surfarray.blit_array()` | Optimized C-level copy, single call |
| Frame rate limiting | `time.sleep()` loop | Vsync (preferred) or `pygame.time.Clock.tick()` | Sleep has 16ms minimum on Windows; vsync is hardware-accurate |

**Key insight:** Every optimization in Phase 4 has a well-established library solution. The engineering challenge is integration (making pygame-ce coexist with cv2-headless, converting bytearrays to numpy for Numba, threading the capture without race conditions) -- not algorithm invention.

## Common Pitfalls

### Pitfall 1: pygame-ce / opencv-python Package Conflict
**What goes wrong:** Installing both `pygame-ce` and `opencv-python` (non-headless) causes SDL2 display subsystem conflicts. Both try to initialize display backends.
**Why it happens:** `opencv-python` bundles its own GUI (highgui) with GTK/Qt dependencies that conflict with pygame-ce's SDL2.
**How to avoid:** Use `opencv-python-headless` (provides `cv2` without GUI) when pygame-ce handles display. Update `pyproject.toml` to depend on `opencv-python-headless` instead of `opencv-python`.
**Warning signs:** Segfaults on `pygame.display.set_mode()`, black windows, frozen display.

### Pitfall 2: pygame surfarray Axis Order (Width-First)
**What goes wrong:** Image appears rotated 90 degrees or transposed on screen.
**Why it happens:** pygame surfarray uses (width, height, 3) axis order; numpy/OpenCV uses (height, width, 3). Every frame must be transposed.
**How to avoid:** Either: (a) transpose with `.transpose(1, 0, 2)` before `blit_array`, or (b) generate frames directly in pygame axis order to eliminate the transpose overhead.
**Warning signs:** Image appears sideways or mirrored.

### Pitfall 3: Numba First-Call Compilation Latency
**What goes wrong:** First frame takes 1-3 seconds to process; all subsequent frames are fast.
**Why it happens:** Numba JIT-compiles on first invocation with a given type signature.
**How to avoid:** Add a warmup call during initialization: `xor_into(np.zeros(16, np.uint8), np.zeros(16, np.uint8))` before entering the main loop. This triggers compilation while the user is waiting for "Press any key to start."
**Warning signs:** Sporadic latency spike on first fountain droplet.

### Pitfall 4: Numba Does Not Support bytearray
**What goes wrong:** `numba.core.errors.TypingError: Failed in nopython mode pipeline` when passing Python `bytearray` to an @njit function.
**Why it happens:** Numba only supports numpy arrays, not Python buffer types.
**How to avoid:** The FountainDecoder must store chunks as `np.ndarray(dtype=np.uint8)` instead of `bytearray`. Convert at ingestion: `np.frombuffer(data, dtype=np.uint8).copy()`.
**Warning signs:** TypingError at runtime on first call.

### Pitfall 5: Deque Popleft on Empty Buffer
**What goes wrong:** `IndexError` when `popleft()` is called on an empty deque.
**Why it happens:** Receiver reads faster than capture thread fills the buffer (startup race or camera stall).
**How to avoid:** Always check `if self._buffer:` before `popleft()`, or use try/except IndexError. The `ThreadedCapture.read()` method should return `(False, None)` when empty.
**Warning signs:** Crash during first few frames of capture.

### Pitfall 6: GIL and Threaded Capture Performance
**What goes wrong:** Adding a capture thread doesn't improve FPS.
**Why it happens:** If processing (decode, XOR) holds the GIL too long, the capture thread can't run.
**How to avoid:** The GIL is released during cv2.VideoCapture.read() (I/O operation) and during numpy operations. Numba @njit functions also release the GIL when `nogil=True` is set. The hot XOR loop should use `@njit(nogil=True)` to allow the capture thread to run concurrently.
**Warning signs:** Measured capture FPS is lower than expected even with threading.

### Pitfall 7: BGR vs RGB Color Order
**What goes wrong:** Colors are swapped (blue becomes red) when displaying via pygame.
**Why it happens:** OpenCV uses BGR; pygame uses RGB.
**How to avoid:** Apply `frame[:, :, ::-1]` (channel reversal) before sending to pygame. For frames generated from bit patterns (fountain/sequential), this may not matter since we use 0 or 255 on all channels, but it matters for debug overlays and calibration screens.
**Warning signs:** Red/blue calibration corners appear swapped.

## Code Examples

### 3bpp Fountain Encode (replacing 1bpp)
```python
# Source: Existing SequentialProtocol.encode_frame pattern
# Replaces FountainProtocol.encode_frame 1bpp path

# Current fountain capacity constants (must be updated):
FOUNTAIN_BYTES_PER_FRAME_3BPP = (config.ROWS * config.COLS * 3) // 8  # 12150
PAYLOAD_SIZE_3BPP = FOUNTAIN_BYTES_PER_FRAME_3BPP - FOUNT_HEADER_SIZE  # 12138

# Encode: bytes -> 3bpp RGB blocks
byte_arr = np.frombuffer(frame_bytes, dtype=np.uint8)
bits = np.unpackbits(byte_arr)
total_bits = config.BLOCKS_PER_FRAME * 3  # 97200
if len(bits) < total_bits:
    bits = np.pad(bits, (0, total_bits - len(bits)), 'constant')
pixel_bits = bits[:total_bits].reshape((config.BLOCKS_PER_FRAME, 3))
rgb = (pixel_bits * 255).astype(np.uint8)
blocks_grid = rgb.reshape((config.ROWS, config.COLS, 3))
# Scale up to full resolution
frame_img = cv2.resize(blocks_grid, (config.WIDTH, config.HEIGHT),
                       interpolation=cv2.INTER_NEAREST)
```

### 3bpp Fountain Decode (replacing 1bpp)
```python
# Source: Existing SequentialProtocol.decode_frame pattern
# Replaces FountainProtocol.decode_frame threshold path

# Current 1bpp: threshold green channel only, pack 1 bit per block
# New 3bpp: threshold all 3 channels, pack 3 bits per block
flat = sampled_grid.reshape(-1, 3)
bits = (flat > 128).astype(np.uint8)  # threshold all channels
flat_bits = bits.reshape(-1)           # interleaved R,G,B bits
raw_bytes = np.packbits(flat_bits).tobytes()
```

### Numba XOR with nogil for Threaded Pipeline
```python
# Source: Numba docs (https://numba.readthedocs.io/en/stable/user/parallel.html)
import numpy as np
from numba import njit

@njit(nogil=True)
def xor_into(dst, src):
    """In-place XOR: dst ^= src. Releases GIL for concurrent capture thread."""
    for i in range(len(dst)):
        dst[i] ^= src[i]

# Usage in FountainDecoder (chunks stored as np.uint8 arrays):
# xor_into(current_data, self.chunks[idx])
```

### FPS Measurement Reporter
```python
# Source: Python stdlib (time.perf_counter_ns docs)
import time

class FPSReporter:
    """Measures and reports actual FPS over a sliding window."""
    def __init__(self, report_interval_s: float = 1.0):
        self._interval_ns = int(report_interval_s * 1e9)
        self._frame_count = 0
        self._start_ns = time.perf_counter_ns()
        self._total_frames = 0

    def tick(self) -> float | None:
        """Call once per frame. Returns FPS when interval elapses, else None."""
        self._frame_count += 1
        self._total_frames += 1
        now = time.perf_counter_ns()
        elapsed = now - self._start_ns
        if elapsed >= self._interval_ns:
            fps = self._frame_count / (elapsed / 1e9)
            self._frame_count = 0
            self._start_ns = now
            return fps
        return None

    @property
    def total_frames(self) -> int:
        return self._total_frames
```

### Pygame Renderer with Pre-allocated Surface
```python
# Source: pygame-ce docs (https://pyga.me/docs/ref/surfarray.html)
import pygame
import numpy as np

class PygameRenderer:
    def __init__(self, width, height):
        pygame.init()
        self._screen = pygame.display.set_mode(
            (width, height), pygame.FULLSCREEN | pygame.NOFRAME, vsync=1
        )
        # Pre-allocate: avoids per-frame Surface creation
        self._surface = pygame.Surface((width, height))
        self._width = width
        self._height = height

    def show_array(self, frame_whc: np.ndarray):
        """Display a (width, height, 3) uint8 array. Already in pygame axis order."""
        pygame.surfarray.blit_array(self._surface, frame_whc)
        self._screen.blit(self._surface, (0, 0))
        pygame.display.flip()  # blocks until vsync
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| cv2.imshow for display | pygame-ce SDL2 with vsync | SDL2 matured in pygame-ce 2.x (2023+) | Removes ~80fps ceiling, enables 120/144/240fps |
| Pure Python byte XOR loops | Numba @njit compiled loops | Numba stable since 0.50+ (2020+) | 100x+ speedup on XOR hot path |
| Blocking cap.read() in main thread | Threaded capture with deque ring buffer | Pattern well-established (pyimagesearch 2017+) | Eliminates I/O stalls, measured FPS reporting |
| 1bpp fountain encoding | 3bpp fountain encoding | Project decision (Phase 4) | 3x per-frame data capacity |
| opencv-python (with GUI) | opencv-python-headless | Always available | No display library conflicts with pygame |

**Deprecated/outdated:**
- `cv2.imshow` for high-FPS display: Not designed for production rendering. `waitKey(1)` has 12-13ms minimum delay. Use pygame-ce SDL2 or Qt/OpenGL.
- `pygame.HWSURFACE` flag: Obsolete in pygame 2+. SDL2 handles hardware acceleration automatically.
- `time.time()` for benchmarking: Non-monotonic, lower precision. Use `time.perf_counter_ns()`.

## Open Questions

1. **Monitor positioning with pygame-ce**
   - What we know: `SDL_VIDEO_WINDOW_POS` environment variable can position the window before `set_mode`. `pygame.display.set_mode(display=N)` can target a specific monitor index.
   - What's unclear: Whether `display=N` parameter works reliably across Linux window managers (X11, Wayland) for multi-monitor setups. The existing `get_monitors()` function returns monitor geometries -- may need to use `SDL_VIDEO_WINDOW_POS` with those coordinates.
   - Recommendation: Implement both approaches (display index and explicit coordinates), prefer display index, fallback to coordinate positioning.

2. **Numba warmup timing**
   - What we know: First @njit call triggers LLVM compilation (1-3 seconds). The sender already shows a "Press any key to start" screen.
   - What's unclear: Whether warmup during calibration screen is sufficient, or if it noticeably delays startup.
   - Recommendation: Trigger warmup of `xor_into` during initialization (tiny dummy arrays). The compilation time for a simple XOR function should be <1 second.

3. **Frame generation in pygame axis order**
   - What we know: Transposing every frame adds ~10-15% overhead. Generating frames directly in (W,H,3) order would eliminate this.
   - What's unclear: Whether the encode_frame path can practically generate (W,H,3) output without breaking the existing decode path that expects (H,W,3) from cv2.
   - Recommendation: Keep encode output as (H,W,3) for decoder compatibility. The sender transposes before display. The ~10% penalty is acceptable since the frame generation itself is numpy vectorized and fast.

4. **ThreadedCapture buffer sizing**
   - What we know: deque(maxlen=64) is a common default. Too small = dropped frames. Too large = stale frames.
   - What's unclear: Optimal buffer size for 240fps capture with 1080p frames (each ~6MB). 64 frames = ~384MB memory.
   - Recommendation: Default to 16 frames (~96MB). This provides ~67ms of buffering at 240fps, enough to absorb processing spikes without excessive memory use. Make buffer_size configurable.

5. **Interaction between Numba nogil and Python threading**
   - What we know: `@njit(nogil=True)` releases the GIL during execution. The capture thread calls cv2.VideoCapture.read() which also releases the GIL (C extension I/O).
   - What's unclear: Whether there are edge cases where GIL contention between Numba and cv2 could cause issues.
   - Recommendation: This should work well since both operations release the GIL. Test with concurrent capture + decode to verify no starvation.

## Sources

### Primary (HIGH confidence)
- [pygame-ce official display docs](https://pyga.me/docs/ref/display.html) - set_mode vsync, fullscreen flags
- [pygame-ce official surfarray docs](https://pyga.me/docs/ref/surfarray.html) - blit_array, make_surface, axis order
- [Numba official 5-minute guide](https://numba.readthedocs.io/en/stable/user/5minguide.html) - @njit usage, restrictions
- [Numba parallel docs](https://numba.readthedocs.io/en/stable/user/parallel.html) - prange, parallel=True, reductions
- [Numba v0.61.0 release notes](https://numba.readthedocs.io/en/stable/release/0.61.0-notes.html) - Python 3.13 support, NumPy 2.1
- [pygame-ce PyPI](https://pypi.org/project/pygame-ce/) - version 2.5.6 (Oct 2025)
- [Numba PyPI](https://pypi.org/project/numba/) - version 0.63.1 (Dec 2025)
- Codebase analysis: `src/hdmi_exfil/protocols/fountain.py`, `display/renderer.py`, `capture/source.py`, `cli/send.py`, `cli/receive.py`

### Secondary (MEDIUM confidence)
- [PyImageSearch: Faster video FPS with threading](https://pyimagesearch.com/2017/02/06/faster-video-file-fps-with-cv2-videocapture-and-opencv/) - threaded capture pattern
- [PyImageSearch: Increasing webcam FPS](https://pyimagesearch.com/2015/12/21/increasing-webcam-fps-with-python-and-opencv/) - background thread + queue
- [Pysource: Multithreading with OpenCV](https://pysource.com/2024/10/15/increase-opencv-speed-by-2x-with-python-and-multithreading-tutorial/) - 2x speed improvement
- [OpenCV forum: waitKey timing issues](https://answers.opencv.org/question/52774/waitkey1-timing-issues-causing-frame-rate-slow-down-fix/) - 12-13ms minimum delay
- [opencv-python-headless PyPI](https://pypi.org/project/opencv-python-headless/) - headless variant for non-GUI use
- [Karthik Karanth: Drawing numpy arrays with pygame](https://karthikkaranth.me/blog/drawing-pixels-with-python/) - practical surfarray usage

### Tertiary (LOW confidence)
- [pygame-ce GitHub issue #2264](https://github.com/pygame-community/pygame-ce/issues/2264) - import name discussion (pygame vs pygame_ce)
- [Python bug tracker #15330](https://bugs.python.org/issue15330) - deque thread safety discussion

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified via official docs and PyPI; versions confirmed current
- Architecture: HIGH - Patterns derived from codebase analysis + established community patterns
- Pitfalls: HIGH - Package conflicts verified via official docs; axis order verified; Numba bytearray limitation documented
- Code examples: HIGH - Encoding/decoding patterns extracted from existing codebase; pygame/numba patterns from official docs

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (30 days -- stable ecosystem, no breaking changes expected)
