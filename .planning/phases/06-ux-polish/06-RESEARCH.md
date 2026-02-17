# Phase 6: UX & Polish - Research

**Researched:** 2026-02-17
**Domain:** CLI UX, resolution profiles, auto-calibration, benchmarking, progress reporting, JS 3bpp encoding
**Confidence:** HIGH (all findings based on direct codebase analysis; no external libraries required)

## Summary

Phase 6 transforms the tool from a developer-oriented prototype into a user-accessible CLI. The four requirements (UX-01 through UX-04) plus the deferred JS 3bpp blocker cover five distinct work streams that are largely independent of each other.

The biggest architectural challenge is **UX-01 (resolution profiles)**: the current codebase loads encoding parameters (`WIDTH`, `HEIGHT`, `BLOCK_SIZE`) from `constants.json` as module-level constants in `config.py`, which are then imported as globals throughout `sequential.py`, `fountain.py`, `cli/send.py`, and `cli/receive.py`. Supporting multiple resolution profiles (1080p vs 4K, different block sizes, different FPS targets) requires making these parameters runtime-configurable rather than static imports. The cleanest path is a **profile dataclass** that encapsulates all resolution-dependent values, passed as constructor arguments to protocol instances and CLI functions.

UX-02 (calibration), UX-03 (benchmarking), and UX-04 (progress reporting) are more self-contained. Calibration builds on the already-existing `sample_frame()` offset/scale parameters and the old manual keyboard calibration from `receiver_fountain.py`. Benchmarking wraps existing FPS/throughput reporting into a structured JSON output. Progress reporting extends the current `sys.stdout.write(\r...)` pattern with speed and ETA calculations.

The JS 3bpp upgrade is a straightforward canvas rendering change: replace the 1-bit-per-block `BLACK`/`WHITE` drawing with 3-bits-per-block RGB channel drawing, tripling the JS sender payload capacity from 4038 to 12138 bytes.

**Primary recommendation:** Implement profiles as a frozen dataclass containing all resolution-dependent values. Pass profile instances into protocol constructors and CLI entry points instead of importing module-level constants. Keep progress reporting as stdlib-only (no `tqdm` dependency) to match the project's minimal dependency philosophy. Calibration should be automated (display known pattern, analyze captured result) rather than the old manual keyboard approach.

## Standard Stack

### Core

No new external libraries needed. All features use existing dependencies.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | >= 1.24 | Array ops for test patterns, SNR calc, pixel analysis | Already in deps |
| opencv-python-headless | >= 4.0 | Frame capture, resize, image analysis | Already in deps |
| pygame-ce | >= 2.5.0 | High-FPS frame display on sender | Already in deps |
| argparse | stdlib | CLI argument parsing with profile presets | Zero dependency |
| json | stdlib | Benchmark JSON output | Zero dependency |
| dataclasses | stdlib | Profile definition, benchmark results | Zero dependency |
| time | stdlib | Speed/ETA calculations | Zero dependency |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sys | stdlib | stdout progress reporting | Progress lines with `\r` |
| struct | stdlib | Header packing/unpacking (already used) | Protocol encode/decode |
| math | stdlib | ETA calculations, ceil | Progress reporting |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom progress reporting | tqdm | Adds dependency for minimal benefit; current `sys.stdout.write` pattern is sufficient and consistent with project style |
| Dict-based profiles | YAML/TOML config files | Overkill; 3 named profiles don't justify config file parsing |
| ConfigArgParse | argparse | Project already uses argparse; adding ConfigArgParse for 1 flag is unnecessary |

**Installation:** No new packages needed.

## Architecture Patterns

### Recommended Project Structure Changes

```
src/hdmi_exfil/
  config.py              # MODIFIED: add ResolutionProfile dataclass + PROFILES dict
  cli/
    send.py              # MODIFIED: add --profile flag, pass profile to protocol
    receive.py           # MODIFIED: add --profile flag, progress tracker
    calibrate.py         # NEW: calibration mode entry point
    benchmark.py         # NEW: benchmark mode entry point
  capture/
    sampler.py           # UNCHANGED: already supports offset/scale params
  display/
    test_patterns.py     # NEW: generate known calibration patterns
  protocols/
    sequential.py        # MODIFIED: accept profile params instead of module constants
    fountain.py          # MODIFIED: accept profile params instead of module constants
```

### Pattern 1: Resolution Profile Dataclass

**What:** A frozen dataclass encapsulating all resolution-dependent encoding parameters. Three named presets map to preconfigured instances.

**When to use:** Everywhere that currently imports `WIDTH`, `HEIGHT`, `BLOCK_SIZE`, `COLS`, `ROWS`, `BYTES_PER_FRAME`, or `PAYLOAD_SIZE` from `config.py`.

**Design:**
```python
# config.py
from dataclasses import dataclass

@dataclass(frozen=True)
class ResolutionProfile:
    """Encoding resolution profile with all derived values."""
    name: str
    width: int
    height: int
    block_size: int
    target_fps: int

    @property
    def cols(self) -> int:
        return self.width // self.block_size

    @property
    def rows(self) -> int:
        return self.height // self.block_size

    @property
    def blocks_per_frame(self) -> int:
        return self.cols * self.rows

    @property
    def bits_per_frame(self) -> int:
        return self.blocks_per_frame * 3  # 3bpp

    @property
    def seq_bytes_per_frame(self) -> int:
        return (self.bits_per_frame // 8) - HEADER_SIZE  # 17-byte header

    @property
    def fount_bytes_per_frame(self) -> int:
        return (self.bits_per_frame // 8) - FOUNT_HEADER_SIZE  # 12-byte header

PROFILES = {
    "speed": ResolutionProfile(
        name="speed",
        width=1920, height=1080, block_size=8,
        target_fps=240,
    ),
    "balanced": ResolutionProfile(
        name="balanced",
        width=1920, height=1080, block_size=8,
        target_fps=60,
    ),
    "quality": ResolutionProfile(
        name="quality",
        width=3840, height=2160, block_size=8,
        target_fps=30,
    ),
}

DEFAULT_PROFILE = PROFILES["speed"]
```

**Key insight:** The `speed` and `balanced` profiles share the same resolution (1080p) but differ in FPS. The `quality` profile uses 4K resolution which quadruples the data per frame (4x pixels = 4x bits = 4x bytes). For 4K:
- Blocks: 480 cols x 270 rows = 129,600 blocks
- Bits: 129,600 * 3 = 388,800 bits
- Bytes/frame: 48,600 bytes (vs 12,150 for 1080p)
- Sequential payload: 48,583 bytes (vs 12,133 for 1080p)
- Fountain payload: 48,588 bytes (vs 12,138 for 1080p)

**Backward compatibility:** Keep current module-level constants in `config.py` as aliases pointing to `DEFAULT_PROFILE` properties. This means existing code continues working without modification during the transition. The `constants.json` file retains its role as the single source of truth for the default profile.

### Pattern 2: Protocol Constructor Injection

**What:** Protocol classes accept an optional `ResolutionProfile` parameter at construction time, defaulting to the current constants for backward compatibility.

**Design:**
```python
class SequentialProtocol(EncodingProtocol):
    def __init__(self, profile: ResolutionProfile | None = None) -> None:
        self._profile = profile or DEFAULT_PROFILE

    @property
    def bytes_per_frame(self) -> int:
        return self._profile.seq_bytes_per_frame

    def encode_frame(self, data, frame_index, total_frames, **kwargs):
        p = self._profile
        # Use p.rows, p.cols, p.width, p.height, p.blocks_per_frame
        # instead of module-level ROWS, COLS, WIDTH, HEIGHT, BLOCKS_PER_FRAME
        ...
```

**Why:** This avoids breaking existing code. `SequentialProtocol()` with no args uses current constants. `SequentialProtocol(profile=PROFILES["quality"])` uses 4K.

### Pattern 3: Progress Tracker

**What:** A lightweight class that tracks frames, bytes, time, and computes speed + ETA. No external dependencies.

**Design:**
```python
class ProgressTracker:
    """Real-time progress tracker for transfer operations."""

    def __init__(self, total_items: int, total_bytes: int) -> None:
        self._total_items = total_items
        self._total_bytes = total_bytes
        self._received = 0
        self._bytes_received = 0
        self._start_ns = time.perf_counter_ns()
        self._last_report_ns = self._start_ns

    def update(self, items: int = 1, bytes_count: int = 0) -> None:
        self._received += items
        self._bytes_received += bytes_count

    @property
    def progress_pct(self) -> float:
        return self._received / self._total_items if self._total_items else 0.0

    @property
    def speed_bytes_per_sec(self) -> float:
        elapsed = (time.perf_counter_ns() - self._start_ns) / 1e9
        return self._bytes_received / elapsed if elapsed > 0 else 0.0

    @property
    def eta_seconds(self) -> float:
        speed = self.speed_bytes_per_sec
        if speed <= 0:
            return float('inf')
        remaining = self._total_bytes - self._bytes_received
        return remaining / speed

    def format_line(self, capture_fps: str = "") -> str:
        pct = self.progress_pct
        speed = self.speed_bytes_per_sec
        eta = self.eta_seconds
        return (
            f"\rFrames: {self._received}/{self._total_items} "
            f"({pct:.1%}) | "
            f"{speed / 1024:.1f} KB/s | "
            f"ETA: {self._format_eta(eta)}"
            f"{capture_fps}"
        )

    @staticmethod
    def _format_eta(seconds: float) -> str:
        if seconds == float('inf'):
            return "--:--"
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"
```

### Pattern 4: Calibration Test Pattern

**What:** Sender displays a deterministic pixel pattern. Receiver captures it, analyzes alignment and signal quality.

**Design for test pattern:**
- Use an alternating checkerboard at block-size granularity (odd blocks white, even blocks black)
- Encode a known byte sequence (e.g., 0xAA = 10101010 binary) into the standard encoding format
- The receiver can then compare expected vs actual pixel values to compute:
  - **Alignment offset:** cross-correlation of expected vs captured pattern to find (dx, dy)
  - **SNR:** mean(signal) / std(noise) on the thresholded channel values
  - **Optimal block size:** test multiple block sizes, find which gives cleanest decode

**Design for auto-alignment:**
```python
def auto_calibrate(frame: np.ndarray, expected_pattern: np.ndarray,
                   block_size: int) -> dict:
    """Analyze captured calibration frame and return optimal parameters.

    Returns dict with keys:
        offset_x, offset_y: pixel alignment offset
        scale_x, scale_y: block spacing scale factor
        snr_db: signal-to-noise ratio in dB
        recommended_block_size: optimal block size
        confidence: HIGH/MEDIUM/LOW
    """
    # 1. Convert both to grayscale
    # 2. Compute normalized cross-correlation to find offset
    # 3. For SNR: sample block centers, measure separation between
    #    "should be white" and "should be black" populations
    # 4. SNR = 20 * log10(mean_signal_diff / std_noise)
    ...
```

### Pattern 5: Benchmark JSON Output

**What:** Automated throughput measurement outputting structured JSON.

**Design:**
```python
@dataclass
class BenchmarkResult:
    """Structured benchmark measurement result."""
    profile: str
    mode: str  # "sequential" or "fountain"
    frames_per_sec: float
    bytes_per_sec: float
    overhead_pct: float  # fountain only
    error_rate: float
    duration_sec: float
    total_frames: int
    total_bytes: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)
```

Benchmark mode should:
1. Generate a known test payload (random bytes of configurable size)
2. Encode frames in a tight loop (no display delay)
3. For loopback: encode -> sample -> decode in memory
4. Measure wall-clock time for the full pipeline
5. Compute frames/sec, bytes/sec, overhead (fountain), error rate
6. Output JSON to stdout or file

### Anti-Patterns to Avoid

- **Global mutable state for profiles:** Do NOT use a global `set_profile()` function that mutates module-level constants at runtime. This creates hard-to-debug state bugs and breaks test isolation. Always pass profile as constructor argument.
- **Adding tqdm/rich as dependencies:** The project has a deliberate minimal dependency philosophy. Progress reporting with `sys.stdout.write` and `\r` is sufficient and keeps the tool lightweight.
- **Overcomplicating JS 3bpp:** The JS sender does NOT need to be refactored into modules. It is a single-file browser tool. Just update the encoding math and drawing loop in-place.
- **OpenCV camera calibration for alignment:** Traditional camera calibration (lens distortion, intrinsic matrix) is completely irrelevant here. The capture card does not introduce lens distortion. The only alignment issue is pixel offset/scale between displayed and captured grids.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CRC32 | Custom CRC function | `zlib.crc32` | Already used throughout; battle-tested |
| SHA-256 | Custom hash | `hashlib.sha256` | Already used; stdlib |
| Cross-correlation for alignment | Custom sliding window | `numpy` correlation or `cv2.matchTemplate` | Numerically stable, fast, handles edge cases |
| Argument parsing with presets | Custom parser | `argparse` with `set_defaults()` | Already in use; standard pattern |
| FPS measurement | Custom timer | `FPSReporter` class | Already implemented in `capture/threaded.py` |
| JSON serialization | Custom formatter | `json.dumps` with `dataclasses.asdict` | Stdlib; handles all types cleanly |

**Key insight:** Almost all building blocks already exist in the codebase. The UX phase is primarily about wiring existing capabilities together with better CLI surfaces, not building new core functionality.

## Common Pitfalls

### Pitfall 1: Breaking Module-Level Constant Imports

**What goes wrong:** Replacing `config.py` module-level constants with profile-dependent values breaks every `from hdmi_exfil.config import WIDTH, HEIGHT, ...` import.

**Why it happens:** Python imports are evaluated once at module load time. Changing the source value after import has no effect on already-bound names.

**How to avoid:** Keep module-level constants as backward-compatible aliases to `DEFAULT_PROFILE` properties. Protocol classes and CLI code that need profile awareness receive the profile object via constructor/argument injection. Gradual migration: old code keeps working, new code uses profiles.

**Warning signs:** Tests that import constants directly will not notice profile changes. Ensure profile-aware tests pass the profile explicitly.

### Pitfall 2: Fountain PAYLOAD_SIZE Mismatch Between JS and Python

**What goes wrong:** JS sender uses `PAYLOAD_SIZE=4038` (1bpp), Python receiver expects `PAYLOAD_SIZE=12138` (3bpp). If only JS is updated to 3bpp payload size without also updating the frame encoding to actually use 3 channels, the receiver will get garbage.

**Why it happens:** The JS `drawBits()` function maps 1 bit to 1 block (black or white). For 3bpp, it must map 3 bits to 1 block (R, G, B channels independently). Both the capacity constants AND the rendering logic must change together.

**How to avoid:** Update JS constants and `drawBits()` in a single atomic change. Test by encoding a known payload in JS, capturing the canvas pixel data, and verifying the Python decoder can reconstruct it.

**Warning signs:** CRC failures on the receiver side after JS update -- this means the encoding/decoding format doesn't match.

### Pitfall 3: ETA Instability in Early Frames

**What goes wrong:** ETA flickers wildly during the first few seconds of transfer because speed measurement has insufficient samples.

**Why it happens:** `speed = bytes_received / elapsed_time` produces unreliable values when `elapsed_time` is very small.

**How to avoid:** Apply a minimum warmup period (e.g., 2 seconds) before displaying ETA. During warmup, show `--:--` instead of a number. Optionally use exponential moving average for speed smoothing.

**Warning signs:** ETA showing "999:99" or similar extreme values in the first few frames, then settling down.

### Pitfall 4: 4K Profile Resource Consumption

**What goes wrong:** 4K frames are 3840x2160x3 = 24.9 MB per frame as numpy array. The ring buffer at `buffer_size=16` would consume ~400 MB of RAM.

**Why it happens:** The `quality` profile quadruples the pixel count without adjusting buffer sizing.

**How to avoid:** Either reduce default buffer size for 4K profiles, or make buffer size profile-aware. Document memory requirements per profile.

**Warning signs:** OOM errors or swap thrashing when running with `--profile quality`.

### Pitfall 5: Calibration Pattern Not Surviving HDMI Compression

**What goes wrong:** The Elgato capture card applies chroma subsampling (4:2:0 or 4:2:2) which can subtly shift the apparent center of colored blocks.

**Why it happens:** HDMI capture cards compress the signal, and the compression artifacts affect fine-grained pixel patterns.

**How to avoid:** Use only black (0,0,0) and white (255,255,255) in the calibration test pattern, not colored blocks. Full-white and full-black blocks are minimally affected by chroma subsampling. The actual data transfer uses 0/255 per channel which is maximally robust, but calibration analysis should use the simplest case.

**Warning signs:** Calibration works perfectly in software loopback but gives offset errors on hardware.

## Code Examples

### Profile Selection in CLI (argparse pattern)

```python
# cli/send.py -- add --profile to existing parser
from hdmi_exfil.config import PROFILES, DEFAULT_PROFILE, ResolutionProfile

def _build_parser():
    parser = argparse.ArgumentParser(...)
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default=None,
        help="Resolution profile: speed (1080p@240fps), balanced (1080p@60fps), quality (4K@30fps)",
    )
    # Existing args remain unchanged
    parser.add_argument("--fps", type=int, default=None, ...)
    ...
    return parser

def main():
    args = parser.parse_args()

    # Profile resolution: --profile overrides defaults, --fps overrides profile
    if args.profile:
        profile = PROFILES[args.profile]
    else:
        profile = DEFAULT_PROFILE

    # Individual flag overrides (--fps, --redundancy, etc.) still work
    target_fps = args.fps if args.fps is not None else profile.target_fps
    ...
```

### JS 3bpp drawBits Upgrade

```javascript
// BEFORE (1bpp): 1 bit per block, BLACK or WHITE
const BITS_PER_FRAME = ROWS * COLS;          // 32400
const BYTES_PER_FRAME = BITS_PER_FRAME / 8;  // 4050
function drawBits(bits) {
    let bitIdx = 0;
    for (let r = 0; r < ROWS; r++) {
        for (let c = 0; c < COLS; c++) {
            const color = bits[bitIdx++] ? WHITE : BLACK;
            // fill block with single color
        }
    }
}

// AFTER (3bpp): 3 bits per block, independent R/G/B channels
const BITS_PER_FRAME = ROWS * COLS * 3;       // 97200
const BYTES_PER_FRAME = BITS_PER_FRAME / 8;   // 12150
const PAYLOAD_SIZE = BYTES_PER_FRAME - HEADER_LEN;  // 12138

function drawBits(bits) {
    let bitIdx = 0;
    for (let r = 0; r < ROWS; r++) {
        const startY = r * BLOCK_SIZE;
        for (let c = 0; c < COLS; c++) {
            // Read 3 bits: R, G, B
            const rBit = bits[bitIdx++];
            const gBit = bits[bitIdx++];
            const bBit = bits[bitIdx++];
            // Pack into ABGR uint32 (little-endian: 0xAABBGGRR)
            const color = 0xFF000000
                | ((bBit ? 0xFF : 0x00) << 16)
                | ((gBit ? 0xFF : 0x00) << 8)
                | (rBit ? 0xFF : 0x00);
            const startX = c * BLOCK_SIZE;
            for (let y = 0; y < BLOCK_SIZE; y++) {
                const rowOffset = (startY + y) * WIDTH + startX;
                buf.fill(color, rowOffset, rowOffset + BLOCK_SIZE);
            }
        }
    }
    ctx.putImageData(imageData, 0, 0);
}
```

**Critical note on endianness:** The `Uint32Array` view of canvas `ImageData` uses the platform's native byte order. On little-endian systems (virtually all x86/ARM), the bytes are ordered R, G, B, A in memory, which maps to `0xAABBGGRR` when read as a 32-bit integer. The existing code uses `BLACK = 0xff000000` (alpha=FF, RGB=0) and `WHITE = 0xffffffff` (all channels 0xFF), which are correct for this endianness. The 3bpp upgrade must follow the same convention.

### SNR Calculation for Calibration

```python
def compute_snr(captured_frame: np.ndarray,
                expected_pattern: np.ndarray,
                block_size: int) -> float:
    """Compute signal-to-noise ratio from a calibration capture.

    Parameters
    ----------
    captured_frame : np.ndarray
        Captured frame from the camera, shape (H, W, 3).
    expected_pattern : np.ndarray
        Binary expected pattern (0 or 255), shape (H, W, 3).
    block_size : int
        Size of each encoding block.

    Returns
    -------
    float
        SNR in dB. Values > 20 dB indicate excellent signal quality.
    """
    # Sample block centers from both frames
    rows = captured_frame.shape[0] // block_size
    cols = captured_frame.shape[1] // block_size
    half = block_size // 2

    captured_samples = captured_frame[half::block_size, half::block_size][:rows, :cols]
    expected_samples = expected_pattern[half::block_size, half::block_size][:rows, :cols]

    # Split into "should be 0" and "should be 255" populations
    mask_white = expected_samples > 128
    mask_black = ~mask_white

    captured_flat = captured_samples.astype(float)

    # Signal: mean difference between white and black populations
    mean_white = captured_flat[mask_white].mean() if mask_white.any() else 255.0
    mean_black = captured_flat[mask_black].mean() if mask_black.any() else 0.0
    signal = mean_white - mean_black

    # Noise: combined std of both populations
    std_white = captured_flat[mask_white].std() if mask_white.any() else 0.0
    std_black = captured_flat[mask_black].std() if mask_black.any() else 0.0
    noise = (std_white + std_black) / 2

    if noise < 1e-6:
        return 60.0  # effectively infinite SNR (perfect capture)

    return 20.0 * np.log10(signal / noise)
```

### Benchmark JSON Output

```python
import json
from dataclasses import dataclass, asdict

@dataclass
class BenchmarkResult:
    profile: str
    mode: str
    frames_per_sec: float
    bytes_per_sec: float
    overhead_pct: float
    error_rate: float
    duration_sec: float
    total_frames: int
    total_bytes: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

# Example output:
# {
#   "profile": "speed",
#   "mode": "fountain",
#   "frames_per_sec": 187.3,
#   "bytes_per_sec": 2273094.0,
#   "overhead_pct": 3.2,
#   "error_rate": 0.0,
#   "duration_sec": 5.47,
#   "total_frames": 1024,
#   "total_bytes": 12437312
# }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Module-level constants only | Profile dataclass with named presets | Phase 6 | Enables multi-resolution support |
| Manual keyboard calibration (ijkl/wasd) | Automated calibration via test pattern analysis | Phase 6 | Users no longer need to manually adjust offset/scale |
| Print-only throughput stats at end | Real-time progress with speed + ETA | Phase 6 | Users see transfer progress live |
| JS sender 1bpp encoding | JS sender 3bpp encoding (matches Python) | Phase 6 | 3x throughput increase for browser sender |
| No benchmark mode | Automated benchmark with JSON output | Phase 6 | Reproducible, machine-parseable performance data |

**Deprecated/outdated:**
- Old `receiver_fountain.py` manual calibration (ijkl keys): replaced by automated `hdmi-recv --calibrate`
- 1bpp JS sender encoding: replaced by 3bpp to match Python sender

## Open Questions

1. **4K Capture Card Capability**
   - What we know: The Elgato 4K X supports 4K@30fps passthrough. The capture API (`cv2.VideoCapture`) can request 3840x2160.
   - What's unclear: Whether the capture card actually delivers raw 3840x2160 frames to OpenCV, or whether it downscales internally. The actual pixel format (YUV 4:2:0 vs 4:2:2 at 4K) affects quality.
   - Recommendation: The `quality` profile should work in loopback testing. Hardware validation is needed for the full pipeline. If 4K capture doesn't work reliably, the profile can still be used for sender-only display (receiver would get 1080p downscaled frames from a 4K source).

2. **JS Canvas Endianness**
   - What we know: The `Uint32Array` view of canvas `ImageData` uses platform-native byte order. Nearly all consumer hardware is little-endian.
   - What's unclear: Whether any target platform could be big-endian (unlikely for desktop browsers).
   - Recommendation: Use the same endianness approach as the existing code (`0xFF000000` for alpha). Add a runtime detection comment but don't implement big-endian fallback.

3. **Calibration Accuracy Requirements**
   - What we know: The `sample_frame()` function supports sub-pixel offset. The old manual calibration used integer pixel offsets.
   - What's unclear: What level of sub-pixel accuracy is actually needed. Empirically, integer pixel alignment may be sufficient if the block size is 8px and capture is at native resolution.
   - Recommendation: Start with integer-pixel alignment detection. If error rates are too high, add sub-pixel refinement.

4. **Profile Impact on constants.json and JS Sender**
   - What we know: `constants.json` stores the single default configuration. The JS sender has its own hardcoded constants.
   - What's unclear: Whether JS sender should support profiles too, or remain fixed at one configuration. The JS sender is designed for zero-install simplicity.
   - Recommendation: JS sender gets 3bpp upgrade but stays at 1080p only (matching `speed`/`balanced` profiles). Profile selection is a Python CLI feature only. If a user needs 4K sender, they use the Python sender.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis of all source files in `src/hdmi_exfil/` -- full architecture understood
- `config.py` -- module-level constant loading from `constants.json`
- `cli/send.py`, `cli/receive.py` -- current CLI argument structure and progress reporting
- `protocols/sequential.py`, `protocols/fountain.py` -- encoding/decoding with hardcoded dimensions
- `capture/sampler.py` -- existing offset/scale support (unused in CLI)
- `capture/threaded.py` -- existing `FPSReporter` class
- `sender.html` -- JS 1bpp encoding logic, canvas `Uint32Array` pixel format
- `receiver_fountain.py` (legacy) -- manual keyboard calibration pattern

### Secondary (MEDIUM confidence)
- Python argparse documentation -- `set_defaults()` pattern for presets
- General numpy/OpenCV cross-correlation for alignment detection

### Tertiary (LOW confidence)
- Elgato 4K X 4K capture behavior with OpenCV -- needs hardware validation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies needed, all analysis based on existing code
- Architecture: HIGH -- profile dataclass pattern is well-understood, existing `sample_frame()` offset/scale API already designed for calibration
- Pitfalls: HIGH -- identified from direct code analysis (constant import pattern, JS/Python payload mismatch, 4K memory)
- JS 3bpp: HIGH -- canvas `Uint32Array` endianness matches existing code pattern; change is purely mathematical
- Calibration: MEDIUM -- auto-alignment via cross-correlation is standard technique but needs hardware validation
- 4K profile: MEDIUM -- software path is clear, hardware behavior with capture card is unverified

**Research date:** 2026-02-17
**Valid until:** 2026-03-17 (stable domain; no fast-moving dependencies)
