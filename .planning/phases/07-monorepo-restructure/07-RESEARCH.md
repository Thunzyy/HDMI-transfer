# Phase 7: Monorepo Restructure - Research

**Researched:** 2026-03-02
**Domain:** Python package restructuring, optional dependencies (pip extras), dependency isolation
**Confidence:** HIGH

## Summary

Phase 7 reorganizes the flat `src/` package into three subpackages (`core/`, `sender/`, `receiver/`) so that users can install only the dependencies they need. The sender requires `pygame-ce` and `screeninfo` (no OpenCV), the receiver requires `opencv-python` (no pygame), and `core` depends only on `numpy` and `numba`.

The critical blocker is STRUCT-06: both `SequentialProtocol.encode_frame()` and `FountainProtocol.encode_frame()` currently call `cv2.resize(..., interpolation=cv2.INTER_NEAREST)` to upscale the block grid to full resolution. This must be replaced with `np.repeat` before the protocols can live in `core/` without an OpenCV dependency. The pattern already exists in the codebase -- `display/test_patterns.py:generate_checkerboard()` line 53 uses exactly `np.repeat(np.repeat(grid, bs, axis=0), bs, axis=1)`.

The pyproject.toml restructure uses standard `[project.optional-dependencies]` with `sender`, `receiver`, and `all` extras. The existing `[tool.setuptools.package-dir]` mapping (which maps `hdmi_exfil` to `src/`) needs updating to use the standard src-layout with subdirectories under `src/hdmi_exfil/`. All CLI entry points stay identical; only the internal import paths for subpackage modules change.

**Primary recommendation:** Execute the restructure in three stages: (1) replace cv2.resize with np.repeat in protocol encoding, (2) move files into core/sender/receiver directories with __init__.py re-exports, (3) update pyproject.toml with extras and new package list.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| STRUCT-01 | Code organized into core/, sender/, receiver/ subpackages | Dependency map below identifies exactly which files belong where |
| STRUCT-02 | `pip install hdmi-exfil[sender]` installs pygame-ce + screeninfo, not opencv | pyproject.toml extras pattern documented; sender files isolated |
| STRUCT-03 | `pip install hdmi-exfil[receiver]` installs opencv-python, not pygame-ce | pyproject.toml extras pattern documented; receiver files isolated |
| STRUCT-04 | `pip install hdmi-exfil` or `[all]` installs everything | `all` extra combines sender + receiver deps |
| STRUCT-05 | Existing CLI commands work unchanged | Entry points stay identical; re-export modules ensure import compatibility |
| STRUCT-06 | cv2.resize replaced with np.repeat in protocol encoding | Pattern verified in existing codebase (test_patterns.py:53) |
| STRUCT-07 | All existing tests pass | Test import updates documented; no logic changes needed |
</phase_requirements>

## Standard Stack

### Core (no changes to external dependencies)
| Library | Version | Purpose | Subpackage |
|---------|---------|---------|------------|
| numpy | >= 1.24 | Array operations, encoding math | core (required) |
| numba | >= 0.60.0 | JIT XOR acceleration | core (required) |

### Sender extras
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| pygame-ce | >= 2.5.0 | SDL2 high-FPS frame display | Sender-only; PygameRenderer |
| screeninfo | >= 0.8 | Cross-platform monitor detection | Sender-only; used in display/monitors.py |

### Receiver extras
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| opencv-python | >= 4.0 | Video capture, frame display, image processing | Receiver-only after STRUCT-06 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single monorepo with extras | Separate PyPI packages | Explicitly out of scope per REQUIREMENTS.md -- more maintenance, version sync burden |
| numpy.kron for upscale | np.repeat | kron works but repeat is simpler and already used in codebase |

## Architecture Patterns

### Current Source Tree (Before)
```
src/
  __init__.py
  config.py
  prng.py
  constants.json
  protocols/
    __init__.py
    base.py
    degree.py
    fountain.py
    sequential.py
    xor_ops.py
  capture/
    __init__.py
    sampler.py
    source.py
    threaded.py
  display/
    __init__.py
    monitors.py
    renderer.py
    test_patterns.py
  file_handling/
    __init__.py
    metadata.py
    reader.py
    writer.py
  cli/
    __init__.py
    benchmark.py
    calibrate.py
    progress.py
    receive.py
    send.py
```

### Target Source Tree (After)
```
src/hdmi_exfil/
  __init__.py              (version, re-exports for backward compat)
  core/
    __init__.py            (re-exports: config, prng, protocols, etc.)
    config.py              (moved from src/config.py)
    prng.py                (moved from src/prng.py)
    constants.json         (moved from src/constants.json)
    protocols/
      __init__.py
      base.py
      degree.py
      fountain.py          (cv2.resize replaced with np.repeat)
      sequential.py        (cv2.resize replaced with np.repeat)
      xor_ops.py
    file_handling/
      __init__.py
      metadata.py
      reader.py
      writer.py
    capture/
      __init__.py
      sampler.py           (cv2.resize replaced with np.repeat)
      threaded.py          (no cv2 dependency -- pure threading)
  sender/
    __init__.py
    display/
      __init__.py
      monitors.py          (screeninfo -- lazy import, already graceful)
      renderer.py          (cv2 + pygame -- both sender-side display)
      test_patterns.py     (no cv2 after np.repeat, but compute_alignment needs cv2)
    cli/
      __init__.py
      send.py
  receiver/
    __init__.py
    capture/
      __init__.py
      source.py            (cv2.VideoCapture -- receiver-only)
    cli/
      __init__.py
      receive.py
      calibrate.py         (cv2 -- receiver-side calibration)
      benchmark.py         (pure compute, but imports sampler which is core)
      progress.py          (pure stdlib)
```

### Dependency Classification (Complete File Audit)

**CORE (numpy + numba only, no cv2/pygame/screeninfo):**

| File | Current Imports | Notes |
|------|----------------|-------|
| config.py | json, struct, importlib.resources | Pure stdlib + json file |
| prng.py | (none external) | Pure Python |
| protocols/base.py | numpy | ABC + FrameResult |
| protocols/degree.py | bisect, math, functools | Pure stdlib math |
| protocols/fountain.py | numpy, config, prng, degree, xor_ops | cv2.resize on line 366-372 MUST be replaced (STRUCT-06) |
| protocols/sequential.py | numpy, struct, zlib, config, metadata, base | cv2.resize on line 128-132 MUST be replaced (STRUCT-06) |
| protocols/xor_ops.py | numpy, numba | Numba JIT |
| file_handling/metadata.py | hashlib, struct | Pure stdlib |
| file_handling/reader.py | os, shutil | Pure stdlib |
| file_handling/writer.py | hashlib, os | Pure stdlib |
| capture/sampler.py | numpy | cv2.resize on line 58-60 as lazy import for frame resize fallback -- replace with np.repeat or numpy indexing |
| capture/threaded.py | threading, time, collections | Pure stdlib (no cv2) |
| cli/progress.py | time | Pure stdlib |

**SENDER (needs pygame-ce + screeninfo):**

| File | HW Dependency | Notes |
|------|---------------|-------|
| display/renderer.py | cv2 (FrameRenderer), pygame (PygameRenderer) | Both renderers are sender-side display |
| display/monitors.py | screeninfo (lazy import with fallback) | Sender-side monitor detection |
| display/test_patterns.py | cv2 in compute_alignment() only | generate_checkerboard is pure numpy; compute_alignment uses cv2.matchTemplate |
| cli/send.py | Uses renderer, monitors, protocols | Wiring layer |

**RECEIVER (needs opencv-python):**

| File | HW Dependency | Notes |
|------|---------------|-------|
| capture/source.py | cv2.VideoCapture | Core receiver capture |
| cli/receive.py | cv2 (resize, imshow, line, destroyAllWindows) | Uses cv2 for debug window + resize |
| cli/calibrate.py | cv2 (VideoCapture, resize, imshow, imwrite) | Receiver-side calibration |

**AMBIGUOUS (needs careful placement):**

| File | Issue | Resolution |
|------|-------|------------|
| cli/benchmark.py | Pure compute -- uses sampler + protocols, no hardware | Move to core/cli/ or keep at top level. No cv2/pygame imports |
| display/test_patterns.py | generate_checkerboard = pure numpy; compute_alignment = cv2 | Split: checkerboard to core, alignment to receiver |
| capture/sampler.py | Pure numpy with cv2 fallback resize | Replace cv2.resize with np.repeat, move to core |
| capture/threaded.py | Pure stdlib threading | Move to core |

### Pattern: Backward-Compatible Re-exports

The top-level `hdmi_exfil` package `__init__.py` and subpackage `__init__.py` files MUST re-export symbols at their old import paths to avoid breaking existing tests and any external users.

```python
# src/hdmi_exfil/__init__.py
"""HDMI Exfiltration - data transfer over HDMI signal encoding."""
__version__ = "0.1.0"

# Backward-compatible re-exports: old import paths still work
from hdmi_exfil.core import config  # noqa: F401
from hdmi_exfil.core import prng    # noqa: F401
```

```python
# src/hdmi_exfil/config.py (compatibility shim)
"""Backward-compatible import shim -- delegates to core.config."""
from hdmi_exfil.core.config import *  # noqa: F401,F403
```

This pattern ensures that `from hdmi_exfil.config import ResolutionProfile` continues to work while the canonical location becomes `hdmi_exfil.core.config`.

### Pattern: pyproject.toml Extras

```toml
[project]
name = "hdmi-exfil"
version = "0.1.0"
requires-python = ">= 3.11"
dependencies = [
    "numpy >= 1.24",
    "numba >= 0.60.0",
]

[project.optional-dependencies]
sender = [
    "pygame-ce >= 2.5.0",
    "screeninfo >= 0.8",
]
receiver = [
    "opencv-python >= 4.0",
]
all = [
    "hdmi-exfil[sender]",
    "hdmi-exfil[receiver]",
]
dev = [
    "hdmi-exfil[all]",
    "pytest >= 8.0",
    "hypothesis >= 6.0",
]
```

Self-referencing extras (e.g., `"hdmi-exfil[sender]"` inside `all`) are supported by pip and setuptools. This is the standard DRY pattern for composing extras.

### Pattern: Conditional Entry Points

Entry points in pyproject.toml do NOT support conditional installation based on extras. ALL entry points are always installed. The CLI modules themselves must handle missing dependencies gracefully at runtime.

```python
# src/hdmi_exfil/sender/cli/send.py (top of main())
def main() -> None:
    try:
        from hdmi_exfil.sender.display.renderer import PygameRenderer
    except ImportError:
        print("Error: sender dependencies not installed.")
        print("Run: pip install hdmi-exfil[sender]")
        sys.exit(1)
    # ... rest of main
```

However, for this project, a simpler approach works: since the CLI imports happen at module level in the current code, a user who installs only `[receiver]` and runs `hdmi-send` will get a clean ImportError. We can add a try/except wrapper in main() for a user-friendly message, but it is not strictly required for STRUCT-05 (which only requires existing commands work -- and they will, with the correct extras installed).

### Pattern: cv2.resize to np.repeat Replacement (STRUCT-06)

The current code upscales a `(rows, cols, 3)` grid to `(height, width, 3)` using:
```python
img = cv2.resize(grid, (width, height), interpolation=cv2.INTER_NEAREST)
```

Since `block_size` is always an integer divisor of both width and height (enforced by the ResolutionProfile), the nearest-neighbor upscale is equivalent to:
```python
img = np.repeat(np.repeat(grid, block_size, axis=0), block_size, axis=1)
# Trim to exact dimensions (safety, in case rows*bs > height)
img = img[:height, :width, :]
```

This pattern is already proven in `display/test_patterns.py:generate_checkerboard()` (line 53).

For `capture/sampler.py`, the cv2.resize is used to DOWNSCALE a captured frame when dimensions don't match. The replacement is either:
1. Use numpy slicing/indexing (nearest-neighbor downsample)
2. Use `frame[::scale_y, ::scale_x]` for integer-factor downsample
3. Use general numpy interpolation for non-integer factors

Given that profile dimensions are always exact multiples of block_size, and capture devices are configured to match the profile dimensions, the resize fallback in sampler.py is a rare edge case. The simplest fix: use `np.repeat` for upscale or numpy fancy indexing for downsample.

### Anti-Patterns to Avoid

- **Circular imports between subpackages:** Core must NOT import from sender or receiver. Sender/receiver import from core only. Never sender<->receiver.
- **Breaking test imports:** Tests import `from hdmi_exfil.protocols.sequential import ...`. If the canonical path changes, compatibility shims MUST be in place.
- **Moving files without updating `__init__.py` re-exports:** Every `__init__.py` must be carefully updated to expose the same public API.
- **Forgetting `[tool.setuptools.package-data]`:** The `constants.json` file must be included via package-data for the new core subpackage path.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Conditional dependency installation | Custom install scripts | pyproject.toml `[project.optional-dependencies]` | Standard pip/setuptools mechanism |
| Package discovery | Manual package list | `setuptools.find_packages` or explicit list | Must list all subpackages including nested ones |
| Nearest-neighbor upscale | Custom pixel loop | `np.repeat(np.repeat(grid, factor, axis=0), factor, axis=1)` | Already proven in codebase, zero dependencies beyond numpy |
| Import compatibility | Manual import mapping | `__init__.py` wildcard re-exports | Standard Python package pattern |

**Key insight:** This restructure is purely organizational -- no logic changes, no new features. The only code change is replacing 3 instances of `cv2.resize` with `np.repeat` and updating import paths. Resist the urge to refactor business logic.

## Common Pitfalls

### Pitfall 1: importlib.resources Path Changes
**What goes wrong:** `config.py` loads `constants.json` via `importlib.resources.files("hdmi_exfil").joinpath("constants.json")`. After the move, the file will be at `hdmi_exfil/core/constants.json`, so the resource path must change to `files("hdmi_exfil.core")`.
**Why it happens:** `importlib.resources.files()` resolves relative to the named package, not the parent.
**How to avoid:** Update the `files()` call in config.py when moving it to core/.
**Warning signs:** `FileNotFoundError` or `ModuleNotFoundError` when importing config.

### Pitfall 2: setuptools Package List Must Be Exhaustive
**What goes wrong:** setuptools `packages` list must include EVERY subpackage, including deeply nested ones like `hdmi_exfil.core.protocols`.
**Why it happens:** setuptools does not auto-discover nested packages unless using `find_packages()` or `find:`.
**How to avoid:** Use `[tool.setuptools.packages.find]` with `where = ["src"]` instead of manually listing packages. Or be exhaustive in the manual list.
**Warning signs:** `ModuleNotFoundError` for subpackage imports after `pip install`.

### Pitfall 3: Forgotten package-data for constants.json
**What goes wrong:** `constants.json` is not included in the built wheel/sdist.
**Why it happens:** `package-data` path must match the new location.
**How to avoid:** Update `[tool.setuptools.package-data]` to point to `hdmi_exfil.core = ["constants.json"]`.
**Warning signs:** Works in editable mode (`pip install -e .`) but fails in regular install.

### Pitfall 4: Test Import Breakage
**What goes wrong:** Tests use paths like `from hdmi_exfil.protocols.sequential import SequentialProtocol`. After restructure, the canonical path becomes `hdmi_exfil.core.protocols.sequential`.
**Why it happens:** Files moved but old import paths not shimmed.
**How to avoid:** Create compatibility modules at old paths that re-export from new locations. Alternatively, create `__init__.py` files at the old paths that do `from hdmi_exfil.core.protocols import *`.
**Warning signs:** `ModuleNotFoundError` in test suite immediately after restructure.

### Pitfall 5: Entry Point Module Paths
**What goes wrong:** Entry points like `hdmi-send = "hdmi_exfil.cli.send:main"` break because `cli/send.py` moved to `sender/cli/send.py`.
**Why it happens:** Entry point paths must match actual module locations.
**How to avoid:** Either update entry points to new paths, or keep shim modules at old paths.
**Warning signs:** `hdmi-send` command fails with import error after reinstall.

### Pitfall 6: np.repeat Produces Wrong Shape When Block Size Doesn't Divide Evenly
**What goes wrong:** `np.repeat(grid, bs, axis=0)` produces `rows * bs` height which may exceed `profile.height`.
**Why it happens:** If `rows * block_size != height` (which shouldn't happen but is a safety concern).
**How to avoid:** Add a trim: `img = img[:height, :width, :]` after repeat (same as test_patterns.py does).
**Warning signs:** Shape mismatch errors in frame display.

## Code Examples

### Example 1: cv2.resize Replacement (STRUCT-06)

Before (sequential.py line 124-132):
```python
import cv2

blocks_grid = pixel_values.reshape(
    (self._profile.rows, self._profile.cols, 3),
).astype(np.uint8)
img: np.ndarray = cv2.resize(
    blocks_grid,
    (self._profile.width, self._profile.height),
    interpolation=cv2.INTER_NEAREST,
)
```

After:
```python
# No cv2 import needed
blocks_grid = pixel_values.reshape(
    (self._profile.rows, self._profile.cols, 3),
).astype(np.uint8)
img = np.repeat(
    np.repeat(blocks_grid, self._profile.block_size, axis=0),
    self._profile.block_size,
    axis=1,
)
# Safety trim to exact profile dimensions
img = img[: self._profile.height, : self._profile.width, :]
```

Source: Verified pattern from `src/display/test_patterns.py` line 53.

### Example 2: pyproject.toml Extras Structure

```toml
[project.optional-dependencies]
sender = [
    "pygame-ce >= 2.5.0",
    "screeninfo >= 0.8",
]
receiver = [
    "opencv-python >= 4.0",
]
all = [
    "hdmi-exfil[sender]",
    "hdmi-exfil[receiver]",
]
dev = [
    "hdmi-exfil[all]",
    "pytest >= 8.0",
    "hypothesis >= 6.0",
]
```

Source: [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/), [setuptools docs](https://setuptools.pypa.io/en/latest/userguide/dependency_management.html)

### Example 3: Backward-Compatible Shim Module

```python
# src/hdmi_exfil/protocols/__init__.py (shim at old path)
"""Backward-compatible re-export -- canonical location is core.protocols."""
from hdmi_exfil.core.protocols import *  # noqa: F401,F403
from hdmi_exfil.core.protocols import (
    EncodingProtocol,
    FrameResult,
    FountainDecoder,
    FountainProtocol,
    PROTOCOLS,
    SequentialProtocol,
    TransferState,
    get_protocol,
    __all__,
)
```

### Example 4: Package Auto-Discovery

```toml
[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-dir]
"" = "src"

[tool.setuptools.package-data]
"hdmi_exfil.core" = ["constants.json"]
```

This replaces the manual package list and auto-discovers all subpackages under `src/`.

### Example 5: sampler.py cv2.resize Replacement

Before:
```python
if frame.shape[0] != expected_h or frame.shape[1] != expected_w:
    import cv2
    frame = cv2.resize(frame, (expected_w, expected_h))
```

After (for the downsample case in receiver):
```python
if frame.shape[0] != expected_h or frame.shape[1] != expected_w:
    # Nearest-neighbor resize using numpy indexing
    src_h, src_w = frame.shape[:2]
    row_idx = np.linspace(0, src_h - 1, expected_h, dtype=int)
    col_idx = np.linspace(0, src_w - 1, expected_w, dtype=int)
    frame = frame[row_idx[:, None], col_idx[None, :]]
```

This is a pure-numpy nearest-neighbor resize that works for both upscale and downscale, removing the cv2 dependency from sampler.py so it can live in core.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual package list in pyproject.toml | `[tool.setuptools.packages.find]` | setuptools 61+ | Auto-discovery avoids missing subpackages |
| `setup.py` extras_require | `[project.optional-dependencies]` in pyproject.toml | PEP 621 (2021) | Standard declarative config |
| Self-referencing extras not supported | `"hdmi-exfil[sender]"` in `all` extra | pip 21.2+ | DRY extras composition |

## Revised File Placement Decision

After thorough analysis, here is the EXACT placement for every file:

### core/ (numpy + numba only)
- `config.py` -- pure stdlib + json
- `prng.py` -- pure Python
- `constants.json` -- data file
- `protocols/` -- entire directory (after cv2.resize removal)
- `file_handling/` -- entire directory (pure stdlib)
- `capture/sampler.py` -- pure numpy (after cv2.resize removal)
- `capture/threaded.py` -- pure stdlib threading
- `cli/progress.py` -- pure stdlib
- `cli/benchmark.py` -- pure compute, imports from core only

### sender/ (needs pygame-ce + screeninfo)
- `display/renderer.py` -- cv2 FrameRenderer + pygame PygameRenderer
- `display/monitors.py` -- screeninfo (lazy import)
- `display/test_patterns.py` -- BUT split needed: `generate_checkerboard` and `compute_snr` are pure numpy, `compute_alignment` uses cv2
- `cli/send.py` -- wiring layer

### receiver/ (needs opencv-python)
- `capture/source.py` -- cv2.VideoCapture
- `cli/receive.py` -- cv2 debug window + frame processing
- `cli/calibrate.py` -- cv2 capture + display

### Special Cases

**display/test_patterns.py:** This file has mixed dependencies:
- `generate_checkerboard()` -- pure numpy (core)
- `compute_snr()` -- pure numpy (core)
- `compute_alignment()` -- uses cv2.matchTemplate (receiver)
- `generate_known_payload()` -- imports SequentialProtocol (core)

Recommendation: Keep `generate_checkerboard`, `compute_snr`, and `generate_known_payload` in core (they are used by benchmarking and calibration). Move `compute_alignment` to receiver (only used by calibrate recv/loopback).

**display/renderer.py:** Has BOTH FrameRenderer (cv2) and PygameRenderer (pygame). Both are sender-side display renderers. The cv2-based FrameRenderer could be used for calibrate-send too. Keep both in sender/. The receiver uses cv2.imshow directly (not through FrameRenderer).

**cli/benchmark.py:** Pure computational benchmark -- no hardware. Uses `sample_frame` (core after cv2 removal) and `get_protocol` (core). Place in core/cli/.

## Open Questions

1. **Compatibility shim depth: module-level or package-level?**
   - What we know: Tests import from paths like `hdmi_exfil.protocols.sequential`, `hdmi_exfil.config`, `hdmi_exfil.capture.sampler`
   - What's unclear: Whether to maintain full shim modules at every old path, or update test imports
   - Recommendation: Create shim `__init__.py` files at old paths for backward compat. This is safer and lower risk than updating 100+ import lines in tests. Tests can be migrated to new paths in a future phase if desired.

2. **FrameRenderer (cv2-based) in sender subpackage**
   - What we know: FrameRenderer uses cv2, which is a receiver dependency. But it is used for sender-side display.
   - What's unclear: Should sender depend on cv2 too?
   - Recommendation: No. FrameRenderer is legacy (capped at ~80fps). The pygame renderer replaced it. Keep FrameRenderer in sender/ with a lazy cv2 import and document that `--renderer cv2` requires `[all]` or manual cv2 install. OR move FrameRenderer to a shared location. Simplest: keep in sender/ with lazy import, it gracefully errors if cv2 absent.

## Sources

### Primary (HIGH confidence)
- **Existing codebase** -- complete file-by-file audit of all 26 source files and 16 test files
- **pyproject.toml** -- current package configuration analyzed
- [Python Packaging User Guide - pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) -- extras syntax
- [setuptools dependency management docs](https://setuptools.pypa.io/en/latest/userguide/dependency_management.html) -- optional dependencies

### Secondary (MEDIUM confidence)
- [setuptools discussions on extras composition](https://github.com/pypa/setuptools/discussions/3627) -- self-referencing extras pattern
- [Hynek Schlawack - Recursive Optional Dependencies](https://hynek.me/articles/python-recursive-optional-dependencies/) -- DRY extras patterns

### Tertiary (LOW confidence)
- None -- all findings verified against codebase or official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- dependencies are already known and in use; just reclassifying them
- Architecture: HIGH -- complete file-by-file audit performed; every import analyzed
- Pitfalls: HIGH -- based on direct codebase analysis, not hypothetical scenarios
- STRUCT-06 (cv2.resize replacement): HIGH -- exact replacement pattern already proven in codebase

**Research date:** 2026-03-02
**Valid until:** Indefinite (setuptools/pip extras are stable specifications)
