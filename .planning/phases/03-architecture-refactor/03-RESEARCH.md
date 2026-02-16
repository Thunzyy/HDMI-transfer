# Phase 3: Architecture Refactor - Research

**Researched:** 2026-02-16
**Domain:** Python packaging, module architecture, protocol abstraction, cross-platform I/O
**Confidence:** HIGH

## Summary

This phase transforms a flat-file Python prototype into a proper src-layout package with clean module boundaries, protocol abstraction via ABC, shared constants between Python and JavaScript, cross-platform capture support, and CLI entry points. The codebase currently has 5 Python files and 1 HTML file at the root with `from common import *` wildcard imports, duplicated `sample_frame()` implementations, Windows-hardcoded capture backends, and constants duplicated between Python and JavaScript.

The standard approach is well-established: pyproject.toml with setuptools as build backend, src-layout for proper import isolation during testing, ABC for the strategy pattern (two protocol implementations sharing one interface), a single constants.json as the cross-language source of truth, and `sys.platform`-based backend selection for OpenCV capture. There are no novel or uncertain technical components -- this is a straightforward restructuring task.

**Primary recommendation:** Use setuptools with pyproject.toml, src-layout with `hdmi_exfil` as the package name, ABC for EncodingProtocol, constants.json at project root, and `[project.scripts]` for CLI entry points. Build bottom-up: foundation modules first (config, protocol ABC, PRNG), then protocol implementations, then I/O layer, then CLI orchestration, and finally the web sender build script.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| setuptools | >= 61.0 | Build backend for pyproject.toml | PyPA standard, already installed (v78.1.1 on this system), supports src-layout auto-discovery |
| pytest | >= 8.0 | Test framework (already in use) | Already configured, supports importlib import mode for src-layout |
| argparse | stdlib | CLI argument parsing | Already in use, zero dependencies, sufficient for flat argument structure |
| json | stdlib | Load constants.json at runtime | Native to both Python and JavaScript, zero dependencies |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| screeninfo | >= 0.8 | Cross-platform monitor detection | Replace ctypes.windll in sender display module -- works on Windows/Linux/macOS |
| hypothesis | >= 6.0 | Property-based testing (already in use) | Continue using for protocol round-trip tests |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| setuptools | hatchling or flit | Smaller/newer but setuptools already installed and well-understood; no benefit for this project |
| ABC | typing.Protocol (PEP 544) | Protocol is for structural subtyping / duck typing; ABC is correct here because we control both implementations and want shared base class logic |
| screeninfo | tkinter.winfo_screenwidth() | tkinter returns combined dimensions on multi-monitor Linux/Mac; screeninfo gives per-monitor resolution and position |
| argparse | click / typer | Overkill for two flat commands; argparse is stdlib and already used |
| constants.json | reconstant | JSON is natively parseable by both Python and JavaScript; reconstant adds a dependency for no benefit |

**Installation (updated requirements):**
```bash
pip install -e ".[dev]"
```

No new runtime dependencies beyond opencv-python and numpy. `screeninfo` is the only new runtime addition (for monitor detection). Development dependencies (pytest, hypothesis) move into pyproject.toml optional dependencies.

## Architecture Patterns

### Recommended Project Structure

```
HDMI_exfil/
├── pyproject.toml                    # Build config, deps, entry points, tool config
├── constants.json                    # Single source of truth for all encoding params
├── src/
│   └── hdmi_exfil/
│       ├── __init__.py               # Package version
│       ├── config.py                 # Load constants.json, derive computed values
│       ├── prng.py                   # SplitMix32 PRNG (shared by fountain protocol)
│       ├── protocols/
│       │   ├── __init__.py           # Protocol registry (dict mapping names to classes)
│       │   ├── base.py               # EncodingProtocol ABC + data classes
│       │   ├── sequential.py         # Sequential 3-bit encoder/decoder
│       │   └── fountain.py           # Fountain encoder/decoder + FountainDecoder
│       ├── capture/
│       │   ├── __init__.py
│       │   ├── source.py             # Cross-platform VideoCapture wrapper
│       │   └── sampler.py            # Block sampling + thresholding (unified)
│       ├── display/
│       │   ├── __init__.py
│       │   ├── renderer.py           # Frame display via OpenCV fullscreen
│       │   └── monitors.py           # Cross-platform monitor detection
│       ├── file_handling/
│       │   ├── __init__.py
│       │   ├── reader.py             # File/directory reading, zip packaging
│       │   ├── writer.py             # Safe file writing with path sanitization
│       │   └── metadata.py           # START payload / fountain metadata pack/unpack
│       └── cli/
│           ├── __init__.py
│           ├── send.py               # hdmi-send command (thin orchestrator)
│           └── receive.py            # hdmi-recv command (thin orchestrator)
├── web/
│   ├── sender.template.html          # HTML template with {{PLACEHOLDER}} markers
│   └── build_sender.py              # Script: reads constants.json, injects into template
├── sender.html                       # Pre-built artifact (committed, generated by build script)
├── tests/
│   ├── conftest.py                   # Shared fixtures, pytest config helpers
│   ├── data/
│   │   └── prng_vectors.json        # PRNG cross-language test vectors
│   ├── test_sequential.py           # Sequential protocol tests
│   ├── test_fountain.py             # Fountain protocol tests
│   ├── test_prng.py                 # PRNG correctness tests
│   ├── test_properties.py           # Hypothesis property-based tests
│   ├── test_loopback.py             # In-memory + hardware loopback
│   ├── test_config.py               # Config loading, constants derivation
│   ├── test_sampler.py              # Block sampling correctness
│   └── test_capture.py              # Capture backend detection tests
├── scripts/
│   └── generate_vectors.js           # JS PRNG test vector generator
├── README.md
├── .gitignore
└── received_files/                   # Default output directory
```

**Key structural decisions:**
- `web/` directory holds the HTML template and build script (NOT inside the Python package -- it is a build artifact, not a runtime dependency)
- `sender.html` at project root is the pre-built artifact (committed for convenience, regenerated by build script)
- Tests stay flat in `tests/` (no unit/integration split yet -- the project is small enough)
- `protocols/base.py` contains the ABC (not `protocol.py` at package root) to keep the protocols package self-contained

### Pattern 1: EncodingProtocol ABC (Strategy Pattern)

**What:** Abstract base class defining the encode/decode interface that both sequential and fountain protocols implement.
**When to use:** When you have 2+ encoding strategies that must be swappable via CLI flag.

```python
# src/hdmi_exfil/protocols/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np

@dataclass
class FrameResult:
    """Result of decoding a single captured frame."""
    data: bytes | None
    frame_type: int | None
    frame_index: int | None
    total_frames: int | None
    is_valid: bool

class EncodingProtocol(ABC):
    """Base class for all encoding strategies."""

    @abstractmethod
    def encode_frame(self, data: bytes, frame_index: int,
                     total_frames: int, **kwargs) -> np.ndarray:
        """Encode a data chunk into a displayable frame image.

        Returns: numpy array of shape (HEIGHT, WIDTH, 3), dtype uint8.
        """
        ...

    @abstractmethod
    def decode_frame(self, sampled_grid: np.ndarray) -> FrameResult:
        """Decode a sampled block grid into data.

        Args:
            sampled_grid: numpy array of shape (ROWS, COLS, 3), dtype uint8.

        Returns: FrameResult with decoded data or is_valid=False.
        """
        ...

    @property
    @abstractmethod
    def bytes_per_frame(self) -> int:
        """Maximum payload capacity per frame in bytes."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable protocol name for CLI display."""
        ...
```

**Source:** [abc module docs](https://docs.python.org/3/library/abc.html), [Refactoring Guru Strategy Pattern](https://refactoring.guru/design-patterns/strategy/python/example)

### Pattern 2: Configuration from constants.json

**What:** Single JSON file defining all encoding parameters. Python loads it at import time, deriving computed values. Build script injects values into sender.html template.

```python
# src/hdmi_exfil/config.py
import json
from pathlib import Path
from dataclasses import dataclass

_CONSTANTS_PATH = Path(__file__).parent.parent.parent / "constants.json"

@dataclass(frozen=True)
class EncodingConfig:
    """Immutable encoding configuration loaded from constants.json."""
    width: int
    height: int
    block_size: int
    seq_magic: int
    fountain_magic: int
    threshold: int

    @property
    def cols(self) -> int:
        return self.width // self.block_size

    @property
    def rows(self) -> int:
        return self.height // self.block_size

    @property
    def blocks_per_frame(self) -> int:
        return self.cols * self.rows

def load_config(path: Path | None = None) -> EncodingConfig:
    """Load encoding configuration from constants.json."""
    if path is None:
        path = _CONSTANTS_PATH
    with open(path) as f:
        raw = json.load(f)
    return EncodingConfig(**raw)
```

```json
// constants.json
{
    "width": 1920,
    "height": 1080,
    "block_size": 8,
    "seq_magic": 55930,
    "fountain_magic": 61632,
    "threshold": 128
}
```

### Pattern 3: Cross-Platform Capture Backend

**What:** Auto-detect the correct OpenCV capture backend based on `sys.platform`.

```python
# src/hdmi_exfil/capture/source.py
import sys
import cv2

def get_capture_backend() -> int:
    """Return the appropriate OpenCV capture backend for the current OS."""
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    elif sys.platform == "linux":
        return cv2.CAP_V4L2
    elif sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY

class CaptureSource:
    """Platform-aware OpenCV VideoCapture wrapper with fallback."""

    def __init__(self, source: int | str, width: int = 1920,
                 height: int = 1080, fps: int = 60):
        backend = get_capture_backend()
        self.cap = cv2.VideoCapture(source, backend)
        if not self.cap.isOpened():
            # Fallback to auto-detect
            self.cap = cv2.VideoCapture(source, cv2.CAP_ANY)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"Could not open video source {source} with any backend"
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)

    def read(self):
        return self.cap.read()

    def release(self):
        self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()
```

**Source:** [OpenCV VideoCapture API Backends](https://docs.opencv.org/3.4/d4/d15/group__videoio__flags__base.html)

### Pattern 4: CLI Entry Points via pyproject.toml

**What:** Two console_scripts entry points that create `hdmi-send` and `hdmi-recv` commands.

```toml
# pyproject.toml
[project.scripts]
hdmi-send = "hdmi_exfil.cli.send:main"
hdmi-recv = "hdmi_exfil.cli.receive:main"
```

```python
# src/hdmi_exfil/cli/send.py
import argparse
from hdmi_exfil.protocols import get_protocol

def main():
    parser = argparse.ArgumentParser(description="HDMI Exfiltration Sender")
    parser.add_argument("input_path", help="File or directory to send")
    parser.add_argument("--mode", choices=["sequential", "fountain"],
                        default="sequential")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--redundancy", type=int, default=1)
    parser.add_argument("--screen", type=int, default=0)
    args = parser.parse_args()

    protocol = get_protocol(args.mode)
    # ... wire file reader -> metadata -> protocol -> renderer
```

### Pattern 5: Constants Injection Build Script

**What:** Python script that reads constants.json, replaces template placeholders in sender.template.html, and writes sender.html.

```python
# web/build_sender.py
import json
from pathlib import Path

def build():
    root = Path(__file__).parent.parent
    with open(root / "constants.json") as f:
        constants = json.load(f)

    template = (root / "web" / "sender.template.html").read_text()
    for key, value in constants.items():
        placeholder = f"{{{{CONST_{key.upper()}}}}}"
        template = template.replace(placeholder, str(value))

    (root / "sender.html").write_text(template)
    print(f"Generated sender.html with {len(constants)} constants injected")

if __name__ == "__main__":
    build()
```

### Anti-Patterns to Avoid

- **Wildcard imports (`from common import *`):** Replace with explicit imports from `hdmi_exfil.config` or pass config as parameter. Currently used in all 4 Python source files.
- **God modules:** sender.py currently mixes encoding, display, monitor detection, file I/O, and CLI in 323 lines. Each concern becomes its own module.
- **Duplicated logic:** `sample_frame()` exists in both receiver.py and receiver_fountain.py with different signatures. Unify into `capture/sampler.py`.
- **Hardcoded platform code:** `ctypes.windll` at module level in sender.py crashes on import on Linux. Platform-specific code goes behind `sys.platform` guards or into platform-specific modules.
- **Bare exception swallowing:** `except Exception: pass` in receiver_fountain.py hides all errors. Catch specific exceptions (`struct.error`, `ValueError`).

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-platform monitor detection | ctypes.windll with manual EnumDisplayMonitors | `screeninfo.get_monitors()` | Windows-only ctypes breaks Linux/macOS; screeninfo handles all platforms with per-monitor position data |
| Python package build/install | Manual sys.path manipulation in conftest.py | `pyproject.toml` + `pip install -e .` | conftest.py hack breaks when directory structure changes; editable install is the standard approach |
| Constants sync Python<->JS | Manually keeping two files in sync | Single constants.json + build script | Human error is inevitable; a 20-line build script eliminates the class of bugs entirely |
| Protocol strategy dispatch | if/elif chains in CLI code | Dict registry in `protocols/__init__.py` | Extensible, testable, no modification of dispatch code when adding protocols |

**Key insight:** The project already has all the pieces (two protocols, shared constants, capture logic) -- the refactor is reorganization, not new functionality. The risk is breaking working code, not implementing new algorithms.

## Common Pitfalls

### Pitfall 1: Breaking Test Imports During Migration

**What goes wrong:** Tests currently do `from sender import encode_frame` relying on conftest.py's `sys.path.insert(0, ...)`. After moving to src-layout, these imports break because the package must be installed.
**Why it happens:** src-layout deliberately prevents importing from the working directory. Tests must import from the installed package.
**How to avoid:** Migrate imports incrementally: (1) create pyproject.toml first, (2) `pip install -e .`, (3) update one test file's imports at a time, (4) verify each passes before moving on.
**Warning signs:** `ModuleNotFoundError: No module named 'sender'` -- the old flat imports no longer work.

### Pitfall 2: Circular Imports When Splitting Modules

**What goes wrong:** After splitting receiver.py into capture/sampler.py + protocols/sequential.py + cli/receive.py, circular dependencies emerge (e.g., protocol needs config, config imports from protocol for type hints).
**Why it happens:** The current code avoids this by having everything in one file. Splitting reveals hidden coupling.
**How to avoid:** Build bottom-up: config -> protocol ABC -> protocol implementations -> I/O layer -> CLI. Never import upward in the dependency chain. Use `TYPE_CHECKING` for type-hint-only imports.
**Warning signs:** `ImportError: cannot import name 'X' from partially initialized module 'Y'`

### Pitfall 3: constants.json Path Resolution at Install Time

**What goes wrong:** `Path(__file__).parent.parent.parent / "constants.json"` works in development (editable install) but fails when the package is installed into site-packages because constants.json is not installed alongside the Python modules.
**Why it happens:** JSON files outside the package directory are not included in wheel distributions by default.
**How to avoid:** Either (a) put constants.json inside the package (`src/hdmi_exfil/constants.json`) and use `importlib.resources` to load it, or (b) keep it at project root but include it in the package via `[tool.setuptools.package-data]`. Option (a) is cleaner -- put the JSON inside the package.
**Warning signs:** `FileNotFoundError: constants.json` when running installed CLI commands.

### Pitfall 4: sender.html Import Breaks on Linux

**What goes wrong:** Current sender.py line 13 has `from ctypes import wintypes` at module level. When test_sequential.py does `from sender import encode_frame`, it triggers this import on Linux, causing `ImportError`.
**Why it happens:** Module-level imports execute unconditionally at import time.
**How to avoid:** In the refactored code, Windows-specific monitor detection lives in `display/monitors.py` with `sys.platform` guards. The encode_frame function moves to `protocols/sequential.py` with no Windows dependencies. Tests can import protocol modules without triggering platform-specific code.
**Warning signs:** Tests that worked on Windows fail on Linux CI with `ImportError: No module named '_ctypes'`

### Pitfall 5: Losing Backward Compatibility During Protocol Refactor

**What goes wrong:** Changing the encode/decode function signatures to match the new ABC interface breaks all existing tests. Tests were written against the old function signatures (`decode_frame` returning 4-tuple vs ABC's `FrameResult`).
**Why it happens:** Tight coupling between test code and implementation details.
**How to avoid:** Keep old function signatures as thin wrappers during migration. Or update tests in the same commit as the corresponding code change. Never have a state where code is changed but tests are not updated.
**Warning signs:** 58 test failures after a refactor commit.

### Pitfall 6: Forgetting to Update conftest.py sys.path Hack

**What goes wrong:** After migrating to src-layout with editable install, the old `sys.path.insert(0, ...)` in conftest.py still exists and causes tests to import from the wrong location (project root instead of installed package).
**Why it happens:** The conftest.py hack was a workaround for the flat layout. It must be removed when switching to src-layout.
**How to avoid:** Remove the sys.path manipulation in conftest.py as part of the very first migration task. Replace pytest.ini with `[tool.pytest.ini_options]` in pyproject.toml.
**Warning signs:** Tests pass locally but import the wrong module version; `print(module.__file__)` shows project root path instead of site-packages.

## Code Examples

### Example 1: Protocol Registry

```python
# src/hdmi_exfil/protocols/__init__.py
from hdmi_exfil.protocols.base import EncodingProtocol
from hdmi_exfil.protocols.sequential import SequentialProtocol
from hdmi_exfil.protocols.fountain import FountainProtocol

PROTOCOLS: dict[str, type[EncodingProtocol]] = {
    "sequential": SequentialProtocol,
    "fountain": FountainProtocol,
}

def get_protocol(name: str, **kwargs) -> EncodingProtocol:
    """Get protocol instance by name."""
    if name not in PROTOCOLS:
        raise ValueError(
            f"Unknown protocol '{name}'. Available: {list(PROTOCOLS.keys())}"
        )
    return PROTOCOLS[name](**kwargs)
```

### Example 2: Unified Sampler

```python
# src/hdmi_exfil/capture/sampler.py
import numpy as np

def sample_frame(frame: np.ndarray, rows: int, cols: int,
                 block_size: int, offset_x: int = 0, offset_y: int = 0,
                 scale_x: float = 1.0, scale_y: float = 1.0) -> np.ndarray:
    """Sample block centers from a captured frame.

    Unified implementation replacing the two diverged sample_frame functions
    in the old receiver.py and receiver_fountain.py.

    Returns: numpy array of shape (rows, cols, 3), dtype uint8.
    """
    height, width = frame.shape[:2]
    half_block = block_size // 2

    grid_x = np.arange(cols)
    sample_x = (grid_x * block_size * scale_x + offset_x + half_block).astype(int)

    grid_y = np.arange(rows)
    sample_y = (grid_y * block_size * scale_y + offset_y + half_block).astype(int)

    np.clip(sample_x, 0, width - 1, out=sample_x)
    np.clip(sample_y, 0, height - 1, out=sample_y)

    return frame[sample_y[:, None], sample_x]
```

### Example 3: pyproject.toml (Complete)

```toml
[build-system]
requires = ["setuptools >= 61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "hdmi-exfil"
version = "0.1.0"
description = "Covert data transfer via HDMI video frames"
requires-python = ">= 3.11"
dependencies = [
    "opencv-python >= 4.0",
    "numpy >= 1.24",
    "screeninfo >= 0.8",
]

[project.optional-dependencies]
dev = [
    "pytest >= 8.0",
    "hypothesis >= 6.0",
    "opencv-python-headless >= 4.0",
]

[project.scripts]
hdmi-send = "hdmi_exfil.cli.send:main"
hdmi-recv = "hdmi_exfil.cli.receive:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
hdmi_exfil = ["constants.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--strict-markers", "-v", "--import-mode=importlib"]
markers = [
    "hardware: marks tests requiring Elgato capture card",
]
```

### Example 4: constants.json Inside Package

```python
# src/hdmi_exfil/config.py
import json
from importlib.resources import files

def _load_constants() -> dict:
    """Load constants.json from within the package."""
    ref = files("hdmi_exfil").joinpath("constants.json")
    return json.loads(ref.read_text())

# Module-level singleton (loaded once at import time)
_RAW = _load_constants()

# Expose as module-level constants for backward compatibility
WIDTH = _RAW["width"]
HEIGHT = _RAW["height"]
BLOCK_SIZE = _RAW["block_size"]
# ... derive computed values
COLS = WIDTH // BLOCK_SIZE
ROWS = HEIGHT // BLOCK_SIZE
BLOCKS_PER_FRAME = COLS * ROWS
BITS_PER_FRAME = BLOCKS_PER_FRAME * 3
BYTES_PER_FRAME = (BITS_PER_FRAME // 8)  # protocol headers subtracted by each protocol
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| setup.py + setup.cfg | pyproject.toml (PEP 621) | 2021 (PEP 621 accepted) | All metadata in one file; setuptools >= 61.0 supports it fully |
| pytest sys.path prepend | pytest importlib import mode | pytest 6.0+ | Cleaner import semantics, no sys.path pollution |
| Manual sys.path in conftest.py | Editable install (pip install -e .) | Standard practice since pip 21.3 | Reliable imports, matches production behavior |
| Separate requirements.txt | Dependencies in pyproject.toml | PEP 621 (2021) | Single source of truth for dependencies |
| ctypes.windll for monitor detection | screeninfo library | screeninfo 0.6+ (2020) | Cross-platform, actively maintained |

**Deprecated/outdated:**
- `setup.py` as primary config: Still works but pyproject.toml is the modern standard
- `sys.path.insert` in conftest.py: Unnecessary with editable install + importlib import mode
- `requirements.txt` for app dependencies: Move to pyproject.toml; keep requirements.txt only for pip-compile workflows

## Open Questions

1. **constants.json location: project root vs inside package**
   - What we know: If placed at project root, it is easy for the build script but requires special packaging config to include in wheels. If placed inside the package (`src/hdmi_exfil/constants.json`), `importlib.resources` loads it cleanly.
   - What's unclear: Whether both the build script AND the package need to reference the same file, or if the build script can read from the package location.
   - Recommendation: Place constants.json INSIDE the package at `src/hdmi_exfil/constants.json`. The build script (`web/build_sender.py`) references it via a relative path. Symlink or copy at project root for convenience. This ensures `pip install` distributes the file and `importlib.resources` can load it at runtime.

2. **FrameResult dataclass vs maintaining old tuple returns**
   - What we know: The old code returns 4-tuples and 5-tuples from decode functions. The ABC pattern suggests returning a FrameResult dataclass.
   - What's unclear: Whether to update all 58 tests simultaneously or provide backward-compatible wrappers.
   - Recommendation: Implement the ABC with FrameResult internally but provide backward-compatible module-level functions (e.g., `decode_frame(grid)` that calls the protocol and unpacks the result). Update tests incrementally. Remove compat layer after all tests are migrated.

3. **Whether to split display and capture backends further (e.g., pygame-ce for Phase 4)**
   - What we know: Phase 4 will replace cv2.imshow with pygame-ce for rendering. The display module should be designed with this swap in mind.
   - What's unclear: Whether to create a DisplayBackend ABC now or wait for Phase 4.
   - Recommendation: Create `display/renderer.py` with a simple class wrapping cv2.imshow. Do NOT create an ABC for display backends yet -- that is Phase 4 scope. Keep the interface clean enough that replacing the internals later is straightforward.

4. **How to handle the FOUNTAIN_MAGIC duplicate in common.py and receiver_fountain.py**
   - What we know: `FOUNTAIN_MAGIC = 0xF0C0` is defined in both `common.py` (line 15) and `receiver_fountain.py` (line 14). The fountain-specific constants (FOUNT_HEADER_FMT, etc.) live only in receiver_fountain.py.
   - What's unclear: Whether fountain constants belong in config.py or in protocols/fountain.py.
   - Recommendation: Protocol-specific constants (header formats, header sizes) belong in their protocol module (`protocols/sequential.py`, `protocols/fountain.py`). Shared magic numbers (`SEQ_MAGIC`, `FOUNTAIN_MAGIC`) belong in `config.py` since the routing logic needs both.

## Build Order for Phase 3

This is the dependency-driven order for implementing the refactor:

```
Step 1: Scaffold (no dependencies)
  ├── pyproject.toml
  ├── constants.json (inside package)
  ├── src/hdmi_exfil/__init__.py
  └── src/hdmi_exfil/config.py (loads constants.json)

Step 2: Foundation modules (depends on Step 1)
  ├── src/hdmi_exfil/prng.py (standalone PRNG, moved from receiver_fountain.py)
  ├── src/hdmi_exfil/protocols/base.py (ABC definition)
  ├── src/hdmi_exfil/capture/sampler.py (unified sample_frame)
  └── src/hdmi_exfil/file_handling/metadata.py (START/fountain metadata pack/unpack)

Step 3: Protocol implementations (depends on Step 1 + 2)
  ├── src/hdmi_exfil/protocols/sequential.py (encode_frame + decode_frame)
  ├── src/hdmi_exfil/protocols/fountain.py (FountainDecoder + encode/decode)
  └── src/hdmi_exfil/protocols/__init__.py (registry)

Step 4: I/O layer (depends on Step 1)
  ├── src/hdmi_exfil/capture/source.py (cross-platform VideoCapture)
  ├── src/hdmi_exfil/display/renderer.py (fullscreen frame display)
  ├── src/hdmi_exfil/display/monitors.py (screeninfo-based detection)
  ├── src/hdmi_exfil/file_handling/reader.py (file/dir reading)
  └── src/hdmi_exfil/file_handling/writer.py (safe file writing)

Step 5: CLI orchestration (depends on Step 3 + 4)
  ├── src/hdmi_exfil/cli/send.py
  └── src/hdmi_exfil/cli/receive.py

Step 6: Web sender build (depends on Step 1 constants.json)
  ├── web/sender.template.html
  ├── web/build_sender.py
  └── sender.html (generated)

Step 7: Test migration (parallel with Steps 2-5)
  ├── Remove conftest.py sys.path hack
  ├── Update imports in all test files
  ├── pip install -e .
  └── Verify all 58 tests pass
```

**Critical path:** Steps 1 -> 2 -> 3 -> 5 -> 7 (minimum for working CLI).
Steps 4 and 6 can proceed in parallel once Step 1 is complete.

## Sources

### Primary (HIGH confidence)
- [Python Packaging User Guide: Writing pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) -- pyproject.toml format, project.scripts
- [Python Packaging User Guide: src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) -- layout comparison, import isolation
- [setuptools: Package Discovery](https://setuptools.pypa.io/en/latest/userguide/package_discovery.html) -- where=["src"], auto-discovery, package-data
- [setuptools: Entry Points](https://setuptools.pypa.io/en/latest/userguide/entry_point.html) -- console_scripts via [project.scripts]
- [pytest: Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) -- importlib mode, src-layout testing
- [Python docs: abc module](https://docs.python.org/3/library/abc.html) -- ABC, abstractmethod
- [OpenCV: VideoCapture API Backends](https://docs.opencv.org/3.4/d4/d15/group__videoio__flags__base.html) -- CAP_V4L2, CAP_DSHOW, CAP_AVFOUNDATION, CAP_ANY
- Direct codebase analysis of all source files (common.py, sender.py, receiver.py, receiver_fountain.py, sender.html, all test files)

### Secondary (MEDIUM confidence)
- [Refactoring Guru: Strategy Pattern in Python](https://refactoring.guru/design-patterns/strategy/python/example) -- verified against abc docs
- [screeninfo on PyPI](https://pypi.org/project/screeninfo/) -- cross-platform monitor detection
- [Real Python: Python pyproject.toml](https://realpython.com/python-pyproject-toml/) -- practical guide, cross-referenced with official docs
- [PyOpenSci: Python Package Structure](https://www.pyopensci.org/python-package-guide/package-structure-code/python-package-structure.html) -- src-layout conventions

### Tertiary (LOW confidence)
- [DataCamp: Python Circular Import](https://www.datacamp.com/tutorial/python-circular-import) -- circular import patterns (general advice, not project-specific)
- [cv2-enumerate-cameras on PyPI](https://pypi.org/project/cv2-enumerate-cameras/) -- camera enumeration utility (noted but not recommended for this project)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pyproject.toml, setuptools, ABC are PyPA/stdlib standards with extensive documentation
- Architecture: HIGH -- src-layout is the recommended pattern; the prior architecture research (.planning/research/ARCHITECTURE.md) already validated the module structure
- Pitfalls: HIGH -- identified from direct codebase analysis (known issues like ctypes.windll, sys.path hack, duplicate sample_frame) and established migration patterns
- Build order: HIGH -- derived from actual import dependency analysis of the current codebase

**Research date:** 2026-02-16
**Valid until:** 2026-04-16 (stable domain -- Python packaging changes slowly)
