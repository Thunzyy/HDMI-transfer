# Architecture Patterns

**Domain:** HDMI data exfiltration tool (covert one-way data channel over video signal)
**Researched:** 2026-02-16
**Confidence:** HIGH (based on direct codebase analysis + established Python packaging patterns)

## Current State Analysis

The prototype is a flat file structure with five Python files and one HTML file at the root. Two independent protocols (sequential 3-bit and fountain 1-bit) share only `common.py` constants. There is no module hierarchy, no abstraction layer, and no separation between encoding logic, transport logic, capture logic, and file handling. The sender.html duplicates constants from common.py with no synchronization mechanism.

**Current coupling problems:**
- `sender.py` mixes encoding, display, monitor detection, file I/O, and CLI parsing in one 267-line file
- `receiver.py` mixes capture, decoding, frame sampling, file reassembly, and CLI in one 237-line file
- `receiver_fountain.py` contains the PRNG, FountainDecoder class, frame sampling, and CLI in 324 lines
- `common.py` defines constants for the sequential protocol but the fountain protocol ignores HEADER_SIZE and BYTES_PER_FRAME
- `sender.html` hardcodes all constants inline in JavaScript with no way to keep them in sync

## Recommended Architecture

### Package Layout (src layout)

```
hdmi_exfil/
├── pyproject.toml                    # Build config, dependencies, entry points
├── constants.json                    # Single source of truth for shared constants
├── src/
│   └── hdmi_exfil/
│       ├── __init__.py               # Package version, top-level exports
│       ├── __main__.py               # python -m hdmi_exfil support
│       ├── config.py                 # Configuration loading + resolution profiles
│       ├── protocol.py               # Protocol ABC/Protocol class (the pluggable interface)
│       ├── prng.py                   # SplitMix32 PRNG (shared between protocols)
│       ├── protocols/
│       │   ├── __init__.py           # Protocol registry
│       │   ├── sequential.py         # Sequential 3-bit encoder/decoder
│       │   └── fountain.py           # Fountain code encoder/decoder + FountainDecoder
│       ├── capture/
│       │   ├── __init__.py
│       │   ├── source.py             # Capture card abstraction (OpenCV backend)
│       │   └── sampler.py            # Block sampling logic (with offset/scale)
│       ├── display/
│       │   ├── __init__.py
│       │   ├── renderer.py           # Frame display via OpenCV fullscreen
│       │   └── monitors.py           # Cross-platform monitor detection
│       ├── file_handling/
│       │   ├── __init__.py
│       │   ├── reader.py             # File/directory reading, zip packaging
│       │   ├── writer.py             # Safe file writing with path sanitization
│       │   └── metadata.py           # Filename metadata encoding/decoding
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── send.py               # hdmi-send command
│       │   └── receive.py            # hdmi-receive command
│       └── web/
│           ├── __init__.py
│           ├── sender.html           # Browser fountain sender (generated or static)
│           └── generate_sender.py    # Script to inject constants.json into sender.html
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Shared pytest fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_prng.py             # PRNG correctness + Python/JS parity
│   │   ├── test_sequential.py       # Sequential encode/decode round-trip
│   │   ├── test_fountain.py         # Fountain encode/decode round-trip
│   │   ├── test_sampler.py          # Block sampling correctness
│   │   ├── test_metadata.py         # Filename metadata encode/decode
│   │   └── test_config.py           # Config loading + profile validation
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_loopback.py         # Full encode-display-capture-decode (no hardware)
│   │   └── test_noise.py            # Encode/decode with simulated JPEG artifacts
│   └── hardware/
│       ├── __init__.py
│       └── test_elgato.py           # Manual: real capture card tests
├── scripts/
│   └── generate_web_sender.py       # Build sender.html from template + constants
├── sender.html                       # Pre-built browser sender (committed for convenience)
└── README.md
```

**Why src layout:** Prevents accidental imports from the project root during testing. When you run `pytest`, Python does not have the project root on `sys.path`, so tests always import the installed package. This catches packaging bugs early. This is the established best practice endorsed by PyPA.

**Why pyproject.toml:** Modern Python standard (PEP 621). Replaces setup.py, setup.cfg, and requirements.txt. Defines dependencies, entry points, and tool configuration in one file.

### Component Boundaries

| Component | Responsibility | Communicates With | Does NOT Touch |
|-----------|---------------|-------------------|----------------|
| `config.py` | Load constants.json, define resolution profiles, validate settings | All components read config | Display, capture, file I/O |
| `protocol.py` | Define the abstract encoding strategy interface | Consumed by protocols/, cli/ | Hardware, display, files |
| `protocols/sequential.py` | Encode bytes to 3-bit RGB frame, decode frame to bytes | config, protocol interface | Capture, display, file I/O |
| `protocols/fountain.py` | Fountain encode/decode, FountainDecoder, degree distribution | config, protocol interface, prng | Capture, display, file I/O |
| `prng.py` | SplitMix32 PRNG (deterministic, portable) | fountain.py, sender.html (via constants.json) | Everything else |
| `capture/source.py` | Open capture device, configure resolution/FPS, read frames | config (for resolution) | Encoding, file I/O |
| `capture/sampler.py` | Sample block centers from captured frame, threshold to bits | config (for block size) | Encoding logic, file I/O |
| `display/renderer.py` | Display encoded frames fullscreen via OpenCV | config (for resolution) | Encoding, capture, files |
| `display/monitors.py` | Detect monitors cross-platform | renderer.py | Everything else |
| `file_handling/reader.py` | Read file/directory, auto-zip directories | cli/ | Encoding, display |
| `file_handling/writer.py` | Write received file safely (path sanitized) | cli/ | Encoding, capture |
| `file_handling/metadata.py` | Pack/unpack filename into byte stream | protocols/, file_handling/ | Display, capture |
| `cli/send.py` | Orchestrate: read file -> encode -> display | All sender components | Capture, decoder |
| `cli/receive.py` | Orchestrate: capture -> sample -> decode -> write | All receiver components | Display, encoder |
| `web/sender.html` | Browser-based fountain sender | constants.json (at build time) | Python runtime |

### Data Flow

**Sender Pipeline (Python):**

```
[File/Dir on disk]
       |
       v
  file_handling/reader.py     -- Read bytes, zip if directory
       |
       v
  file_handling/metadata.py   -- Prepend [name_len][name][content]
       |
       v
  protocols/sequential.py     -- Split into chunks, encode each as frame
  OR protocols/fountain.py    -- Split into K chunks, generate droplets
       |
       v
  display/renderer.py         -- Display frame fullscreen on target monitor
       |
       v
  [HDMI signal out]
```

**Sender Pipeline (Browser):**

```
[File selected in browser]
       |
       v
  sender.html (JS)            -- FileReader API -> wrap metadata
       |                       -- Slice into K chunks
       v                       -- SplitMix32 PRNG (same as prng.py)
  sender.html (JS)            -- Build droplet, render to canvas
       |
       v
  [HDMI signal out via display]
```

**Receiver Pipeline:**

```
[HDMI signal in via capture card]
       |
       v
  capture/source.py           -- cv2.VideoCapture, configure resolution/FPS
       |
       v
  capture/sampler.py          -- Sample block centers, threshold to bits/bytes
       |
       v
  protocols/sequential.py     -- Parse header, extract frame data
  OR protocols/fountain.py    -- Parse seed+K, FountainDecoder.add_droplet()
       |
       v
  file_handling/metadata.py   -- Extract filename from reassembled bytes
       |
       v
  file_handling/writer.py     -- Sanitize path, write to output directory
       |
       v
  [File on disk]
```

**Data flow direction is strictly unidirectional:** file -> encode -> display -> HDMI -> capture -> decode -> file. No component communicates backwards (this matches the physical constraint that HDMI is one-way).

## Patterns to Follow

### Pattern 1: Protocol as Strategy (ABC with shared base)

Use an Abstract Base Class rather than a Protocol (PEP 544) because the encoding strategies share common logic (metadata wrapping, frame construction boilerplate) that should live in the base class. Use ABC when you control the hierarchy and want shared implementation; use Protocol when you need duck-typing for external types.

```python
# src/hdmi_exfil/protocol.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np

@dataclass
class EncodedFrame:
    """A single frame ready for display."""
    image: np.ndarray          # (HEIGHT, WIDTH, 3) uint8
    frame_number: int          # For progress tracking
    total_frames: int | None   # None for fountain (rateless)

@dataclass
class DecodedChunk:
    """A chunk extracted from a captured frame."""
    data: bytes
    index: int | None          # Frame index (sequential) or None
    total: int | None          # Total frames (sequential) or K (fountain)
    is_valid: bool             # Whether decode succeeded

class EncodingProtocol(ABC):
    """Base class for all encoding strategies."""

    @abstractmethod
    def encode_frame(self, data: bytes, **kwargs) -> EncodedFrame:
        """Encode a data chunk into a displayable frame."""
        ...

    @abstractmethod
    def decode_frame(self, sampled_grid: np.ndarray) -> DecodedChunk:
        """Decode a sampled block grid into data."""
        ...

    @property
    @abstractmethod
    def bytes_per_frame(self) -> int:
        """Payload capacity per frame in bytes."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable protocol name."""
        ...
```

**Why this works for HDMI exfil:** The two protocols (sequential, fountain) have fundamentally different frame structures and headers, but both follow the same lifecycle: take bytes in, produce a frame image; take a sampled grid, produce bytes out. The ABC enforces this contract while allowing completely different implementations.

### Pattern 2: Configuration as Dataclass with Profiles

Instead of module-level constants scattered across files, use a frozen dataclass loaded from `constants.json`. Profiles capture common resolution/FPS combinations.

```python
# src/hdmi_exfil/config.py
from dataclasses import dataclass
import json
from pathlib import Path

@dataclass(frozen=True)
class ResolutionProfile:
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

# Pre-defined profiles
PROFILES = {
    "1080p_240": ResolutionProfile("1080p@240fps", 1920, 1080, 8, 240),
    "1080p_60":  ResolutionProfile("1080p@60fps",  1920, 1080, 8, 60),
    "4k_30":     ResolutionProfile("4K@30fps",     3840, 2160, 16, 30),
}

def load_config(path: Path | None = None) -> dict:
    """Load constants.json as the shared source of truth."""
    if path is None:
        path = Path(__file__).parent.parent.parent / "constants.json"
    with open(path) as f:
        return json.load(f)
```

**Why frozen dataclass over Pydantic:** This project has no environment variables, no .env files, no complex validation needs. A frozen dataclass is zero-dependency, immutable (safe for concurrent access), and simple. Pydantic would be overkill. If configuration needs grow later, migration to Pydantic BaseSettings is straightforward.

### Pattern 3: Constants.json as Cross-Language Source of Truth

The most critical shared state is the constants (WIDTH, HEIGHT, BLOCK_SIZE, etc.) that must match exactly between the Python receiver and the JavaScript sender. Use a single JSON file as the canonical source.

```json
{
  "width": 1920,
  "height": 1080,
  "block_size": 8,
  "sequential_header_size": 12,
  "fountain_header_size": 6,
  "threshold": 128,
  "prng_seed_bytes": 4,
  "prng_k_bytes": 2,
  "max_k": 60000,
  "max_filename_length": 1024
}
```

**Python side:** `config.py` loads this JSON and derives computed values (cols, rows, bytes_per_frame).

**JavaScript side:** A build script (`scripts/generate_web_sender.py`) reads `constants.json` and injects the values into `sender.html` at a marked template location. Alternatively, the HTML file can load the JSON via a `<script>` tag or inline `fetch()` -- but since the sender must work as a single standalone file (zero install on source machine), the build-time injection approach is correct. The committed `sender.html` at the project root is the pre-built artifact.

**Why JSON over YAML/reconstant:** JSON is natively parseable by both Python (`json.load`) and JavaScript (literal object). No build tools needed for the Python side. The generation script for the JS side is a simple string replacement, under 30 lines.

### Pattern 4: Capture Abstraction for Cross-Platform Support

The current code hardcodes `cv2.CAP_DSHOW` (Windows-only DirectShow). Abstract the capture backend.

```python
# src/hdmi_exfil/capture/source.py
import sys
import cv2

def get_capture_backend() -> int:
    """Return the appropriate OpenCV capture backend for the current platform."""
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    elif sys.platform == "linux":
        return cv2.CAP_V4L2
    elif sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY

class CaptureSource:
    """Abstraction over OpenCV VideoCapture with platform-aware backend."""

    def __init__(self, source: int | str, width: int, height: int, fps: int):
        backend = get_capture_backend()
        self.cap = cv2.VideoCapture(source, backend)
        if not self.cap.isOpened():
            # Fallback to CAP_ANY
            self.cap = cv2.VideoCapture(source, cv2.CAP_ANY)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)

    def read(self):
        return self.cap.read()

    def release(self):
        self.cap.release()

    @property
    def actual_resolution(self) -> tuple[int, int]:
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return (w, h)

    @property
    def actual_fps(self) -> float:
        return self.cap.get(cv2.CAP_PROP_FPS)
```

### Pattern 5: CLI Entry Points via pyproject.toml console_scripts

Use `argparse` (already in the codebase, zero new dependencies) with console_scripts entry points. Each command is a thin orchestrator that wires components together.

```toml
# In pyproject.toml
[project.scripts]
hdmi-send = "hdmi_exfil.cli.send:main"
hdmi-receive = "hdmi_exfil.cli.receive:main"
```

```python
# src/hdmi_exfil/cli/send.py
import argparse
from hdmi_exfil.config import PROFILES
from hdmi_exfil.protocols.sequential import SequentialProtocol
from hdmi_exfil.protocols.fountain import FountainProtocol
from hdmi_exfil.file_handling.reader import read_input
from hdmi_exfil.file_handling.metadata import wrap_with_metadata
from hdmi_exfil.display.renderer import FullscreenRenderer

def main():
    parser = argparse.ArgumentParser(description="HDMI Exfiltration Sender")
    parser.add_argument("input_path", help="File or directory to send")
    parser.add_argument("--mode", choices=["sequential", "fountain"], default="fountain")
    parser.add_argument("--profile", choices=list(PROFILES.keys()), default="1080p_60")
    parser.add_argument("--fps", type=int, help="Override profile FPS")
    parser.add_argument("--redundancy", type=int, default=1)
    parser.add_argument("--screen", type=int, default=0)
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    # ... wire components together
```

**Why argparse over Click/Typer:** The CLI is simple (two commands, flat arguments, no subcommand trees). argparse is stdlib, zero dependencies, already used in the codebase. Click/Typer add complexity without benefit for this use case.

## Anti-Patterns to Avoid

### Anti-Pattern 1: God Module (Current State)

**What:** A single file (e.g., sender.py) that handles CLI parsing, file reading, encoding, display, monitor detection, and progress reporting.

**Why bad:** Cannot test encoding without importing display code. Cannot reuse encoding in a different context (e.g., pre-encode to video file). Any change touches a file that owns too many responsibilities. The current sender.py at 267 lines is already showing strain; adding 4K support and fountain mode to the same file would push it past 500 lines.

**Instead:** Each responsibility becomes a module. The CLI file is a thin orchestrator that creates instances and calls methods.

### Anti-Pattern 2: Wildcard Imports from Configuration

**What:** `from common import *` used in every file.

**Why bad:** Namespace pollution. Cannot tell which constants are actually used by a module. If common.py adds a new name that collides with a local variable, the bug is silent.

**Instead:** Explicit imports: `from hdmi_exfil.config import load_config` or pass a `ResolutionProfile` dataclass to functions that need dimensions.

### Anti-Pattern 3: Duplicating Logic Across Protocol Variants

**What:** `sample_frame()` is implemented twice (receiver.py and receiver_fountain.py) with different signatures and features.

**Why bad:** Fixes and improvements must be applied in two places. The fountain variant has offset/scale tuning that the sequential variant lacks -- not because it doesn't need it, but because no one copied it over.

**Instead:** One `sampler.py` module used by both protocol receivers. The sampler does not know about encoding -- it takes a raw frame and returns a block grid.

### Anti-Pattern 4: Hardcoding Protocol Constants in Multiple Languages

**What:** `sender.html` defines `const WIDTH = 1920; const BLOCK_SIZE = 8;` etc. independently from `common.py`.

**Why bad:** A constant change in Python without updating JavaScript causes silent decode failure. The PRNG implementation is the most dangerous -- if the SplitMix32 constants differ by even one bit, every droplet decodes wrong.

**Instead:** Single `constants.json` source of truth. Build step injects into HTML. PRNG has a dedicated cross-language test that verifies identical output sequences for known seeds.

### Anti-Pattern 5: Bare Exception Swallowing

**What:** `except Exception: pass` in `receiver_fountain.py` lines 316-318.

**Why bad:** Hides every possible error: numpy shape mismatches, struct parse errors, memory errors, keyboard interrupts. Makes debugging impossible during development.

**Instead:** Catch specific exceptions (`struct.error`, `ValueError`, `IndexError`). Log unexpected errors with traceback. Use `--debug` flag to control verbosity.

## Scalability Considerations

| Concern | Current (Prototype) | At 1080p@60fps | At 4K@30fps | At 1080p@240fps |
|---------|---------------------|----------------|-------------|-----------------|
| Frame encoding time | ~2ms (fast enough) | ~2ms OK | ~8ms (larger frame) verify | <4ms required, may need pre-encoding |
| Fountain XOR | Python loop, slow | Bottleneck | Major bottleneck | Critical bottleneck |
| Memory (receiver) | Unbounded droplet list | OK for small files | OK | Risk for >100MB files |
| K field limit | uint16 = 65535 chunks | ~265MB max | ~265MB max | ~265MB max |
| Block alignment | Manual offset tuning | Workable | Needs recalibration | Frame drops mask misalignment |
| Constants sync | Manual duplication | Error-prone | Error-prone | Error-prone |

**Key scaling actions by phase:**
1. **Immediate:** Fix fountain XOR to use numpy (10-100x speedup, unlocks real-world FPS)
2. **Before 4K:** Make resolution profile-driven (block_size, headers, frame capacity derived from profile)
3. **Before 240fps:** Add frame pre-encoding or producer thread to sender
4. **Before large files:** Upgrade K from uint16 to uint32 (header size change cascades to both sender.html and receiver)

## Build Order (Dependencies Between Components)

The restructuring should proceed bottom-up, from zero-dependency modules to orchestration layers. Each phase produces testable, working code.

```
Phase 1: Foundation (no dependencies between these)
  ├── config.py          -- loads constants.json, defines profiles
  ├── prng.py            -- SplitMix32, depends on nothing
  ├── protocol.py        -- ABC definition, depends on nothing
  └── constants.json     -- the source of truth file

Phase 2: Core Logic (depends on Phase 1)
  ├── protocols/sequential.py  -- depends on config, protocol
  ├── protocols/fountain.py    -- depends on config, protocol, prng
  ├── file_handling/metadata.py -- depends on config (header sizes)
  └── capture/sampler.py       -- depends on config (block size, dimensions)

Phase 3: I/O Layer (depends on Phase 1 config)
  ├── capture/source.py        -- depends on config (resolution, fps)
  ├── display/renderer.py      -- depends on config (resolution)
  ├── display/monitors.py      -- depends on nothing (platform detection)
  ├── file_handling/reader.py  -- depends on nothing
  └── file_handling/writer.py  -- depends on nothing

Phase 4: Orchestration (depends on Phase 2 + 3)
  ├── cli/send.py              -- wires reader + metadata + protocol + renderer
  └── cli/receive.py           -- wires source + sampler + protocol + metadata + writer

Phase 5: Web Sender (depends on Phase 1)
  ├── scripts/generate_web_sender.py  -- reads constants.json, outputs sender.html
  └── sender.html                      -- pre-built artifact
```

**Why this order:**
- Phase 1 modules have zero dependencies on each other. They can all be written and tested in parallel.
- Phase 2 modules depend only on Phase 1 abstractions. Tests can use the protocol interface to verify encode/decode round-trips without any hardware, display, or file I/O.
- Phase 3 modules handle real-world I/O but depend only on configuration, not on encoding logic. They can be tested independently (e.g., capture/source.py can be verified by opening a capture device and reading resolution).
- Phase 4 is pure wiring. By the time you write CLI orchestration, every component it calls is already tested.
- Phase 5 is independent of the Python runtime (it is a build artifact). It can be done at any point after constants.json exists.

**Critical path:** Phase 1 -> Phase 2 -> Phase 4. This is the minimum path to a working refactored tool. Phase 3 and Phase 5 can happen in parallel with Phase 2.

## Rationale for Key Decisions

### Why ABC Over typing.Protocol for EncodingProtocol

We control both strategy implementations (sequential and fountain). They will share common logic:
- Frame construction boilerplate (numpy array creation, resize to full resolution)
- Header packing/unpacking helpers
- Progress calculation

ABCs allow putting this shared code in the base class. `typing.Protocol` does not support shared implementation -- it is purely a type-checking construct. Since we are not building a plugin system for external users, the nominal subtyping of ABCs is a feature (explicit contract), not a limitation.

### Why Not a Plugin/Registry System

The project has exactly two encoding protocols. A registry pattern (`protocols/__init__.py` mapping names to classes) is a lightweight convenience for the CLI (`--mode fountain` -> look up class), but a full plugin discovery system (entry_points, importlib.metadata) is unnecessary complexity. Keep it simple: a dict mapping strings to classes.

### Why Separate capture/ and display/ Packages

Capture and display are hardware I/O concerns that should be testable and replaceable independently. A test might use a fake capture source (numpy array) with the real sampler. A benchmark might use the real renderer with dummy encoded frames. Separating them from protocol logic enables all of these compositions without mocking.

### Why file_handling/ as a Separate Package

Both sender and receiver need file operations, but the operations are different:
- Sender: read file, optionally zip directory, wrap with metadata
- Receiver: unwrap metadata, sanitize path, write file

These are shared utilities that do not belong to either the send or receive command. Putting them in a shared package avoids duplication.

## Sources

- [Python Packaging User Guide: src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) -- HIGH confidence
- [Python Packaging User Guide: Writing pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) -- HIGH confidence
- [PEP 544: Protocols: Structural subtyping](https://peps.python.org/pep-0544/) -- HIGH confidence
- [Real Python: Python Protocols](https://realpython.com/python-protocol/) -- HIGH confidence
- [Refactoring Guru: Strategy Pattern in Python](https://refactoring.guru/design-patterns/strategy/python/example) -- HIGH confidence
- [Python Packaging Guide: Creating CLI Tools](https://packaging.python.org/en/latest/guides/creating-command-line-tools/) -- HIGH confidence
- [Spriteware/lt-codes-python](https://github.com/Spriteware/lt-codes-python) -- MEDIUM confidence (reference LT code structure)
- [dbieber/fountaincode](https://github.com/dbieber/fountaincode) -- MEDIUM confidence (reference fountain code structure)
- [Reconstant: Share constants between languages](https://github.com/aantn/reconstant) -- LOW confidence (considered but JSON is simpler)
- Direct codebase analysis of all 6 source files -- HIGH confidence

---

*Architecture research: 2026-02-16*
