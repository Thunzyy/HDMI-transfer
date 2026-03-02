# Architecture Patterns

**Domain:** Interactive CLI consoles and monorepo restructure for HDMI data exfiltration tool
**Researched:** 2026-03-02
**Confidence:** HIGH (direct codebase analysis, established Python packaging patterns, InquirerPy well-known from training data)

## Current State Analysis

The v1.0 architecture is already well-structured with clean module boundaries. The restructure from flat files to `src/` layout was completed in previous phases. The current state:

```
src/
  __init__.py            # hdmi_exfil package root
  config.py              # constants.json loader, ResolutionProfile, PROFILES
  prng.py                # SplitMix32 PRNG, choose_indices (fountain)
  cli/
    __init__.py
    send.py              # hdmi-send entry point (argparse)
    receive.py           # hdmi-recv entry point (argparse)
    calibrate.py         # hdmi-calibrate entry point (argparse)
    benchmark.py         # hdmi-bench entry point (argparse)
    progress.py          # ProgressTracker (shared utility)
  protocols/
    __init__.py          # Protocol registry, get_protocol()
    base.py              # EncodingProtocol ABC, FrameResult
    sequential.py        # SequentialProtocol, TransferState
    fountain.py          # FountainProtocol, FountainDecoder
    degree.py            # Robust Soliton Distribution
    xor_ops.py           # Numba JIT XOR
  capture/
    __init__.py
    source.py            # CaptureSource (cross-platform VideoCapture)
    sampler.py           # sample_frame (block-centre extraction)
    threaded.py          # ThreadedCapture, FPSReporter
  display/
    __init__.py
    renderer.py          # FrameRenderer (cv2), PygameRenderer (SDL2)
    monitors.py          # get_monitors (cross-platform via screeninfo)
    test_patterns.py     # Calibration patterns, SNR, alignment
  file_handling/
    __init__.py
    reader.py            # read_input (file/dir to bytes)
    writer.py            # write_output, verify_integrity
    metadata.py          # START metadata pack/unpack
```

**pyproject.toml mapping:** `hdmi_exfil = "src"` -- flat package-dir, all subpackages listed explicitly.

### What Works Well (Do Not Break)

1. **EncodingProtocol ABC** in `protocols/base.py` -- clean contract, both protocols implement it
2. **ResolutionProfile dataclass** in `config.py` -- immutable, derived properties, all modules parameterized by it
3. **Protocol registry** in `protocols/__init__.py` -- `get_protocol(name, profile=profile)` factory
4. **Separation of concerns** -- CLI files are thin orchestrators, encoding logic is in protocols/, I/O is in capture/ and display/
5. **constants.json** as single source of truth shared with sender.html

### What Needs to Change

1. **No interactive mode** -- all CLI is argparse-only, no menu system
2. **No sender/receiver dependency split** -- installing `hdmi-exfil` pulls ALL dependencies (pygame-ce, numba, opencv, screeninfo) even if you only want receiver
3. **Flat package-dir** -- `hdmi_exfil = "src"` prevents clean namespace splitting into core/sender/receiver

## Recommended Architecture

### Target Package Layout

```
src/
  hdmi_exfil/                       # Renamed: actual Python package directory
    __init__.py                     # Package root, __version__
    core/                           # CORE: shared by both sender and receiver
      __init__.py                   # Re-exports for convenience
      config.py                     # constants.json, ResolutionProfile, PROFILES
      prng.py                       # SplitMix32 PRNG, choose_indices
      protocols/
        __init__.py                 # Protocol registry, get_protocol()
        base.py                     # EncodingProtocol ABC, FrameResult
        sequential.py               # SequentialProtocol, TransferState
        fountain.py                 # FountainProtocol, FountainDecoder
        degree.py                   # Robust Soliton Distribution
        xor_ops.py                  # Numba JIT XOR
      file_handling/
        __init__.py
        reader.py                   # read_input
        writer.py                   # write_output, verify_integrity
        metadata.py                 # Metadata pack/unpack
      capture/                      # Block sampling is shared (benchmark uses it)
        __init__.py
        sampler.py                  # sample_frame
    sender/                         # SENDER: display + sending CLI
      __init__.py
      display/
        __init__.py
        renderer.py                 # FrameRenderer, PygameRenderer
        monitors.py                 # get_monitors
        test_patterns.py            # Calibration patterns
      cli/
        __init__.py
        send.py                     # hdmi-send argparse entry point
        calibrate.py                # hdmi-calibrate entry point
        console.py                  # NEW: interactive sender console
    receiver/                       # RECEIVER: capture + receiving CLI
      __init__.py
      capture/
        __init__.py
        source.py                   # CaptureSource
        threaded.py                 # ThreadedCapture, FPSReporter
      cli/
        __init__.py
        receive.py                  # hdmi-recv argparse entry point
        console.py                  # NEW: interactive receiver console
    cli/                            # SHARED CLI utilities
      __init__.py
      progress.py                   # ProgressTracker
      benchmark.py                  # hdmi-bench entry point (uses core only)
    constants.json                  # Package data (stays with hdmi_exfil)
```

### Why This Split (Not the Obvious One)

The temptation is to put `capture/` under receiver and `display/` under sender. But the dependency analysis reveals nuances:

**capture/sampler.py is CORE:** Both sender (benchmark) and receiver need `sample_frame()`. It has zero hardware dependencies (pure numpy math). Move to `core/capture/`.

**capture/source.py and capture/threaded.py are RECEIVER-ONLY:** They depend on `opencv-python` for `cv2.VideoCapture`. Only the receiver opens a capture device.

**display/ is SENDER-ONLY:** `renderer.py` depends on `pygame-ce` and `opencv-python` for display. `monitors.py` depends on `screeninfo`. Only the sender displays frames.

**test_patterns.py is SENDER-ONLY (mostly):** `generate_checkerboard` is used by `calibrate send` and `calibrate recv`. However, the receiver's calibration analysis (`compute_snr`, `compute_alignment`) needs the expected pattern too. Keep it with sender since the sender generates and the receiver only needs to compare against a known pattern it can import.

**protocols/ is CORE:** Both sides need encode and decode. The sender encodes frames; the receiver decodes them. The benchmark needs both.

**file_handling/ is CORE:** Both sides need metadata. The sender uses `reader.py` + `metadata.py`. The receiver uses `writer.py` + `metadata.py`.

**benchmark.py is SHARED:** It does in-memory encode/decode round-trips (no hardware). Needs `protocols/` + `sampler.py`. Goes in shared `cli/`.

### Component Boundaries

| Component | Responsibility | Dependencies | Package |
|-----------|---------------|--------------|---------|
| `core/config.py` | Load constants, define profiles | stdlib, json | core |
| `core/prng.py` | SplitMix32, index selection | core.protocols.degree | core |
| `core/protocols/base.py` | ABC, FrameResult | numpy | core |
| `core/protocols/sequential.py` | Sequential encode/decode | core.config, core.protocols.base, numpy, cv2 | core |
| `core/protocols/fountain.py` | Fountain encode/decode, FountainDecoder | core.config, core.prng, core.protocols.base, numpy, cv2 | core |
| `core/protocols/degree.py` | RSD CDF + sampling | stdlib only | core |
| `core/protocols/xor_ops.py` | Numba JIT XOR | numba, numpy | core |
| `core/capture/sampler.py` | Block-centre sampling | numpy (cv2 lazy) | core |
| `core/file_handling/reader.py` | File/dir reading | stdlib only | core |
| `core/file_handling/writer.py` | Safe file writing | stdlib only | core |
| `core/file_handling/metadata.py` | Metadata pack/unpack | stdlib only | core |
| `sender/display/renderer.py` | Frame display (cv2 + pygame) | opencv-python, pygame-ce | sender |
| `sender/display/monitors.py` | Monitor detection | screeninfo | sender |
| `sender/display/test_patterns.py` | Calibration patterns | numpy, core.config | sender |
| `sender/cli/send.py` | Send orchestration | core, sender.display | sender |
| `sender/cli/calibrate.py` | Calibration orchestration | core, sender.display, cv2 | sender |
| `sender/cli/console.py` | Interactive sender menu | InquirerPy, core, sender | sender |
| `receiver/capture/source.py` | Capture device wrapper | opencv-python | receiver |
| `receiver/capture/threaded.py` | Threaded capture + FPS | stdlib (threading) | receiver |
| `receiver/cli/receive.py` | Receive orchestration | core, receiver.capture | receiver |
| `receiver/cli/console.py` | Interactive receiver menu | InquirerPy, core, receiver | receiver |
| `cli/progress.py` | Progress tracking | stdlib (time) | shared |
| `cli/benchmark.py` | In-memory benchmark | core only | shared |

### Data Flow (Updated for Consoles)

**Interactive Sender Console Flow:**

```
[User launches: hdmi-sender]
       |
       v
  sender/cli/console.py       -- InquirerPy list prompt
       |
       +--> "Send file (Python)" --> sender/cli/send.py workflow
       |      |
       |      +--> InquirerPy file path prompt (or argument)
       |      +--> InquirerPy list: mode (sequential/fountain)
       |      +--> InquirerPy list: profile (speed/balanced/quality)
       |      +--> Confirmation prompt
       |      +--> Execute existing send pipeline
       |
       +--> "Send file (Browser)" --> webbrowser.open(sender.html path)
       |
       +--> "Calibrate" --> sender/cli/calibrate.py workflow
       |      +--> InquirerPy list: send/recv/loopback
       |
       +--> "Detect hardware" --> sender/display/monitors.py
       |      +--> Print monitor info
       |
       +--> "Benchmark" --> cli/benchmark.py workflow
       |      +--> InquirerPy list: profile
       |      +--> InquirerPy list: mode
       |
       +--> "Settings" --> view/edit profile, FPS, screen target
       |
       +--> "Exit"
```

**Interactive Receiver Console Flow:**

```
[User launches: hdmi-receiver]
       |
       v
  receiver/cli/console.py     -- InquirerPy list prompt
       |
       +--> "Receive file" --> receiver/cli/receive.py workflow
       |      |
       |      +--> InquirerPy number: capture source index
       |      +--> InquirerPy list: mode (auto/sequential/fountain)
       |      +--> InquirerPy list: profile
       |      +--> InquirerPy filepath: output directory
       |      +--> Execute existing receive pipeline
       |
       +--> "Calibrate signal" --> calibrate recv workflow
       |
       +--> "Detect capture card" --> try opening cv2.VideoCapture(0..3)
       |      +--> Print device info
       |
       +--> "Last transfer stats" --> show stored results
       |
       +--> "Settings" --> view/edit profile, buffer size, threaded
       |
       +--> "Exit"
```

### pyproject.toml Extras Structure

```toml
[build-system]
requires = ["setuptools >= 61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "hdmi-exfil"
version = "1.1.0"
description = "Maximum throughput data transfer over HDMI signal encoding"
requires-python = ">= 3.11"

# Core dependencies: needed by ALL installations
dependencies = [
    "numpy >= 1.24",
    "numba >= 0.60.0",
]

[project.optional-dependencies]
# Sender: display + monitor detection + interactive CLI
sender = [
    "opencv-python >= 4.0",
    "pygame-ce >= 2.5.0",
    "screeninfo >= 0.8",
    "InquirerPy >= 0.3.4",
]

# Receiver: capture + interactive CLI
receiver = [
    "opencv-python >= 4.0",
    "InquirerPy >= 0.3.4",
]

# Everything
all = [
    "hdmi-exfil[sender]",
    "hdmi-exfil[receiver]",
]

# Development
dev = [
    "hdmi-exfil[all]",
    "pytest >= 8.0",
    "hypothesis >= 6.0",
]

[project.scripts]
# Original argparse commands (backward compatible)
hdmi-send = "hdmi_exfil.sender.cli.send:main"
hdmi-recv = "hdmi_exfil.receiver.cli.receive:main"
hdmi-calibrate = "hdmi_exfil.sender.cli.calibrate:main"
hdmi-bench = "hdmi_exfil.cli.benchmark:main"

# NEW: Interactive consoles
hdmi-sender = "hdmi_exfil.sender.cli.console:main"
hdmi-receiver = "hdmi_exfil.receiver.cli.console:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"hdmi_exfil" = ["constants.json"]
```

**Key decisions:**

1. **numpy + numba in core deps** because protocols/xor_ops.py is core and both sides need it. Cannot avoid these. opencv-python is the heavy optional dep.

2. **opencv-python in BOTH sender and receiver** because sender uses cv2.resize in encoding (sequential.py, fountain.py) and the cv2 FrameRenderer fallback, while receiver uses cv2.VideoCapture. However, the core protocols also use cv2 for `cv2.resize` in encode. This is a problem -- see the "cv2 in Core" discussion below.

3. **InquirerPy in BOTH extras** because each console is independent.

4. **Self-referencing extras** (`all = ["hdmi-exfil[sender]", ...]`) -- this is a valid PEP 508 pattern supported by pip and setuptools.

### The cv2-in-Core Problem

Both `SequentialProtocol.encode_frame()` and `FountainProtocol.encode_frame()` use `cv2.resize()` for nearest-neighbour upscaling from block grid to full resolution. This means `opencv-python` is effectively a core dependency, not sender-only.

**Three options:**

1. **Accept cv2 as core dep** -- simplest, but means receiver installs display-related code it does not use.
2. **Replace cv2.resize with numpy repeat** -- `np.repeat(np.repeat(grid, bs, axis=0), bs, axis=1)`. This is what `test_patterns.py` already does for checkerboard generation. Zero cv2 dependency for encoding. The receiver only needs decode (no resize), so this change only affects the sender path.
3. **Lazy import cv2 in encode** -- import cv2 only when `encode_frame` is called, which is sender-side only.

**Recommendation: Option 2 (numpy repeat)** because:
- `test_patterns.py` already proves the pattern works
- Removes hidden cv2 coupling from core
- `cv2.INTER_NEAREST` on integer grids with exact multiples produces identical output to `np.repeat`
- The receiver only calls `decode_frame` (no resize), so no cv2 needed in core

After this change, the dependency graph becomes clean:
- **core:** numpy, numba (stdlib otherwise)
- **sender:** core + opencv-python + pygame-ce + screeninfo + InquirerPy
- **receiver:** core + opencv-python + InquirerPy

### Import Path Migration

All existing imports change prefix. This is the highest-risk part of the restructure.

| Old Import | New Import |
|-----------|------------|
| `from hdmi_exfil.config import ...` | `from hdmi_exfil.core.config import ...` |
| `from hdmi_exfil.prng import ...` | `from hdmi_exfil.core.prng import ...` |
| `from hdmi_exfil.protocols import ...` | `from hdmi_exfil.core.protocols import ...` |
| `from hdmi_exfil.protocols.base import ...` | `from hdmi_exfil.core.protocols.base import ...` |
| `from hdmi_exfil.protocols.fountain import ...` | `from hdmi_exfil.core.protocols.fountain import ...` |
| `from hdmi_exfil.protocols.sequential import ...` | `from hdmi_exfil.core.protocols.sequential import ...` |
| `from hdmi_exfil.protocols.xor_ops import ...` | `from hdmi_exfil.core.protocols.xor_ops import ...` |
| `from hdmi_exfil.protocols.degree import ...` | `from hdmi_exfil.core.protocols.degree import ...` |
| `from hdmi_exfil.capture.sampler import ...` | `from hdmi_exfil.core.capture.sampler import ...` |
| `from hdmi_exfil.capture.source import ...` | `from hdmi_exfil.receiver.capture.source import ...` |
| `from hdmi_exfil.capture.threaded import ...` | `from hdmi_exfil.receiver.capture.threaded import ...` |
| `from hdmi_exfil.display.renderer import ...` | `from hdmi_exfil.sender.display.renderer import ...` |
| `from hdmi_exfil.display.monitors import ...` | `from hdmi_exfil.sender.display.monitors import ...` |
| `from hdmi_exfil.display.test_patterns import ...` | `from hdmi_exfil.sender.display.test_patterns import ...` |
| `from hdmi_exfil.file_handling.reader import ...` | `from hdmi_exfil.core.file_handling.reader import ...` |
| `from hdmi_exfil.file_handling.writer import ...` | `from hdmi_exfil.core.file_handling.writer import ...` |
| `from hdmi_exfil.file_handling.metadata import ...` | `from hdmi_exfil.core.file_handling.metadata import ...` |
| `from hdmi_exfil.cli.progress import ...` | `from hdmi_exfil.cli.progress import ...` |
| `from hdmi_exfil.cli.benchmark import ...` | `from hdmi_exfil.cli.benchmark import ...` |
| `from hdmi_exfil.cli.send import ...` | `from hdmi_exfil.sender.cli.send import ...` |
| `from hdmi_exfil.cli.receive import ...` | `from hdmi_exfil.receiver.cli.receive import ...` |
| `from hdmi_exfil.cli.calibrate import ...` | `from hdmi_exfil.sender.cli.calibrate import ...` |

**Backward compatibility shim:** Add re-exports in the old locations during a transition period.

```python
# src/hdmi_exfil/config.py (shim)
"""Backward compatibility shim -- imports from hdmi_exfil.core.config."""
from hdmi_exfil.core.config import *  # noqa: F401,F403
```

This allows existing tests to pass unchanged during the restructure, then shims can be removed in a follow-up commit.

## Interactive Console Architecture

### InquirerPy Integration Pattern

InquirerPy (version 0.3.4+) provides prompt_toolkit-based interactive prompts. It supports:
- **list prompts** -- arrow-key selection from choices (the primary UX)
- **filepath prompts** -- with autocomplete
- **number prompts** -- for numeric input
- **confirm prompts** -- yes/no
- **fuzzy prompts** -- searchable lists

**Console structure (sender example):**

```python
# src/hdmi_exfil/sender/cli/console.py
"""Interactive sender console -- hdmi-sender entry point."""

from __future__ import annotations

import sys

def main() -> None:
    """Launch interactive sender console."""
    try:
        from InquirerPy import inquirer
    except ImportError:
        print("Interactive console requires InquirerPy.")
        print("Install with: pip install hdmi-exfil[sender]")
        sys.exit(1)

    while True:
        action = inquirer.select(
            message="HDMI Sender Console",
            choices=[
                {"name": "Send file (Python)", "value": "send_python"},
                {"name": "Send file (Browser)", "value": "send_browser"},
                {"name": "Calibrate", "value": "calibrate"},
                {"name": "Detect hardware", "value": "detect"},
                {"name": "Benchmark", "value": "benchmark"},
                {"name": "Settings", "value": "settings"},
                {"name": "Exit", "value": "exit"},
            ],
            default="send_python",
        ).execute()

        if action == "exit":
            break
        elif action == "send_python":
            _send_python_flow(inquirer)
        elif action == "send_browser":
            _send_browser_flow()
        # ... etc


def _send_python_flow(inquirer) -> None:
    """Interactive send workflow using InquirerPy prompts."""
    file_path = inquirer.filepath(
        message="File or directory to send:",
        validate=lambda p: len(p) > 0,
    ).execute()

    mode = inquirer.select(
        message="Encoding mode:",
        choices=["fountain", "sequential"],
        default="fountain",
    ).execute()

    profile = inquirer.select(
        message="Resolution profile:",
        choices=[
            {"name": "Speed (1080p @ 240fps)", "value": "speed"},
            {"name": "Balanced (1080p @ 60fps)", "value": "balanced"},
            {"name": "Quality (4K @ 30fps)", "value": "quality"},
        ],
        default="balanced",
    ).execute()

    confirm = inquirer.confirm(
        message=f"Send '{file_path}' via {mode} ({profile})?",
        default=True,
    ).execute()

    if confirm:
        # Build argparse-compatible namespace and delegate to existing send.py
        from hdmi_exfil.sender.cli.send import main as send_main
        sys.argv = [
            "hdmi-send", file_path,
            "--mode", mode,
            "--profile", profile,
        ]
        try:
            send_main()
        except SystemExit:
            pass  # argparse calls sys.exit on completion
```

**Key design decisions:**

1. **Lazy import InquirerPy** -- fail gracefully if not installed, suggest correct pip extras command.

2. **Delegate to existing CLI functions** -- the console does NOT reimplement send/receive logic. It collects parameters interactively, then delegates to the existing argparse-based functions. This avoids code duplication and ensures the console always behaves identically to the direct CLI.

3. **Loop-based menu** -- after each action completes, return to the main menu. Exit explicitly.

4. **No global state** -- each action is independent. Settings can be stored in a simple dict passed between menu iterations.

### Alternative Considered: Rich + simple_term_menu

Rich (for pretty output) + simple_term_menu (for arrow-key selection) was considered. Rejected because:
- Two dependencies instead of one
- InquirerPy provides both prompt types AND styled output
- InquirerPy's prompt_toolkit backend handles terminal resize, unicode, and Windows Terminal compatibility
- InquirerPy has built-in filepath completion, which Rich does not

### Console Entry Point vs Existing Entry Points

The consoles are ADDITIVE. Existing `hdmi-send`, `hdmi-recv`, `hdmi-calibrate`, `hdmi-bench` commands continue to work unchanged with argparse. The new `hdmi-sender` and `hdmi-receiver` commands are the interactive alternatives.

Users who want scriptable/automatable behavior use the original commands.
Users who want guided interactive use launch the consoles.

## Patterns to Follow

### Pattern 1: Graceful Dependency Degradation

Every module that depends on an optional package should fail with a helpful message, not a raw ImportError.

```python
def _check_sender_deps() -> None:
    """Verify sender dependencies are installed."""
    missing = []
    try:
        import pygame  # noqa: F401
    except ImportError:
        missing.append("pygame-ce")
    try:
        import screeninfo  # noqa: F401
    except ImportError:
        missing.append("screeninfo")
    if missing:
        deps = ", ".join(missing)
        raise RuntimeError(
            f"Missing sender dependencies: {deps}\n"
            f"Install with: pip install hdmi-exfil[sender]"
        )
```

### Pattern 2: Console as Thin Orchestrator

The console module collects user input and delegates to existing functions. It never contains encoding, display, capture, or file handling logic.

```
Console: "What do you want to do?" --> collect params --> call existing function
```

This means the console can be tested by mocking InquirerPy prompts and verifying the correct function is called with the correct arguments.

### Pattern 3: Re-export Shims for Backward Compatibility

During the transition, old import paths should work via re-export shims. Each shim is a single-line file that imports from the new location. This allows tests to pass during incremental migration.

```python
# src/hdmi_exfil/config.py (shim during transition)
from hdmi_exfil.core.config import *  # noqa: F401,F403
```

Remove shims after all internal imports are updated and tests pass with new paths.

### Pattern 4: Package-Level Convenience Re-exports

The `core/__init__.py` should re-export commonly used items so downstream code can use shorter paths:

```python
# src/hdmi_exfil/core/__init__.py
from hdmi_exfil.core.config import (
    PROFILES,
    DEFAULT_PROFILE,
    ResolutionProfile,
)
from hdmi_exfil.core.protocols import get_protocol
from hdmi_exfil.core.protocols.base import EncodingProtocol, FrameResult
```

### Pattern 5: Setuptools Package Discovery

Use `find:` packages instead of explicit listing, which breaks when adding new subpackages:

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

This auto-discovers all packages under `src/` by their `__init__.py` files.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Circular Dependencies Between Sender/Receiver

**What:** Receiver imports from sender.display or sender imports from receiver.capture.

**Why bad:** Defeats the purpose of the split. Installing `[receiver]` would pull in sender dependencies.

**Prevention:** Both sender and receiver depend on core. They NEVER import from each other. If shared functionality is discovered, move it to core.

**Detection:** Run `pipdeptree` or `import-linter` to verify no cross-imports.

### Anti-Pattern 2: Console That Reimplements CLI Logic

**What:** The console module duplicates the send/receive pipeline instead of delegating.

**Why bad:** Two code paths to maintain. Bug fixes must be applied twice. Behavior divergence between `hdmi-send` and `hdmi-sender` console mode.

**Prevention:** Console collects parameters, then calls the same `main()` or internal function that argparse calls. Or better: extract the pipeline into a separate function that both argparse and console call.

### Anti-Pattern 3: Moving Files Without Updating All Imports

**What:** Renaming `hdmi_exfil.capture.source` to `hdmi_exfil.receiver.capture.source` but forgetting to update imports in `cli/receive.py`.

**Why bad:** ImportError at runtime. Tests may pass if they import from different paths.

**Prevention:** Use backward-compat shims during transition. Run the full test suite after each file move. Use `grep -r "from hdmi_exfil\." src/` to find all imports.

### Anti-Pattern 4: Over-splitting into Separate Python Packages

**What:** Making `hdmi-exfil-core`, `hdmi-exfil-sender`, `hdmi-exfil-receiver` as three separate PyPI packages.

**Why bad:** Version coordination nightmare. User must ensure compatible versions. Complex publishing workflow. Overkill for a single-repo project.

**Instead:** Single package with extras. One version number. One publish. Extras control which optional dependencies are installed.

## Build Order (Migration Sequence)

The restructure must maintain a passing test suite at every step. Here is the safe incremental sequence:

### Step 1: Create Target Directory Structure (GREEN tests)

Create the new directory tree with `__init__.py` files. Do NOT move any code yet.

```
src/hdmi_exfil/core/__init__.py          (empty)
src/hdmi_exfil/core/protocols/__init__.py (empty)
src/hdmi_exfil/core/capture/__init__.py   (empty)
src/hdmi_exfil/core/file_handling/__init__.py (empty)
src/hdmi_exfil/sender/__init__.py         (empty)
src/hdmi_exfil/sender/display/__init__.py (empty)
src/hdmi_exfil/sender/cli/__init__.py     (empty)
src/hdmi_exfil/receiver/__init__.py       (empty)
src/hdmi_exfil/receiver/capture/__init__.py (empty)
src/hdmi_exfil/receiver/cli/__init__.py   (empty)
```

Tests: ALL PASS (no code moved, no imports changed).

### Step 2: Move Core Modules + Add Shims (GREEN tests)

Move bottom-up (zero-dependency first):

1. `src/config.py` --> `src/hdmi_exfil/core/config.py`
   - Add shim: `src/config.py` with `from hdmi_exfil.core.config import *`

2. `src/prng.py` --> `src/hdmi_exfil/core/prng.py`
   - Add shim at old location

3. `src/protocols/` --> `src/hdmi_exfil/core/protocols/`
   - Add shims at old locations

4. `src/file_handling/` --> `src/hdmi_exfil/core/file_handling/`
   - Add shims at old locations

5. `src/capture/sampler.py` --> `src/hdmi_exfil/core/capture/sampler.py`
   - Add shim at old location

Tests: ALL PASS (shims redirect imports transparently).

**CRITICAL:** Update internal imports within moved files to use new paths. The shims only help external consumers (tests, CLI files).

### Step 3: Move Sender Modules + Add Shims (GREEN tests)

1. `src/display/` --> `src/hdmi_exfil/sender/display/`
2. `src/cli/send.py` --> `src/hdmi_exfil/sender/cli/send.py`
3. `src/cli/calibrate.py` --> `src/hdmi_exfil/sender/cli/calibrate.py`

Add shims at old locations. Update internal imports in moved files.

Tests: ALL PASS.

### Step 4: Move Receiver Modules + Add Shims (GREEN tests)

1. `src/capture/source.py` --> `src/hdmi_exfil/receiver/capture/source.py`
2. `src/capture/threaded.py` --> `src/hdmi_exfil/receiver/capture/threaded.py`
3. `src/cli/receive.py` --> `src/hdmi_exfil/receiver/cli/receive.py`

Add shims at old locations. Update internal imports.

Tests: ALL PASS.

### Step 5: Move Shared CLI + Fix Remaining (GREEN tests)

1. `src/cli/progress.py` stays at `src/hdmi_exfil/cli/progress.py` (already correct path)
2. `src/cli/benchmark.py` stays at `src/hdmi_exfil/cli/benchmark.py`
3. Update `src/hdmi_exfil/cli/__init__.py` if needed

Tests: ALL PASS.

### Step 6: Update pyproject.toml (GREEN tests)

Switch from explicit package list + flat `package-dir` to `find:` packages:

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

Add optional-dependencies sections. Update entry point paths.

Tests: ALL PASS (reinstall with `pip install -e ".[dev]"`).

### Step 7: Remove cv2 from Core Encoding (GREEN tests)

Replace `cv2.resize(..., cv2.INTER_NEAREST)` in `sequential.py` and `fountain.py` with `np.repeat`:

```python
# Before (in encode_frame):
import cv2
frame_img = cv2.resize(blocks_grid, (width, height), interpolation=cv2.INTER_NEAREST)

# After:
bs = self._profile.block_size
frame_img = np.repeat(np.repeat(blocks_grid, bs, axis=0), bs, axis=1)
# Trim if grid*bs != exact resolution
frame_img = frame_img[:self._profile.height, :self._profile.width, :]
```

Tests: ALL PASS (encode/decode round-trips produce identical output since INTER_NEAREST on exact multiples = repeat).

### Step 8: Update All Internal Imports to New Paths (GREEN tests)

Go through every `.py` file and update imports to use `hdmi_exfil.core.`, `hdmi_exfil.sender.`, `hdmi_exfil.receiver.` paths directly. Keep shims in place for now.

Tests: ALL PASS.

### Step 9: Update Test Imports (GREEN tests)

Update all test files to use new import paths.

Tests: ALL PASS.

### Step 10: Remove Shims (GREEN tests)

Delete the old shim files that redirect to new locations. Now the old paths no longer work.

Tests: ALL PASS (all imports were updated in steps 8-9).

### Step 11: Add Interactive Consoles (NEW feature)

1. Create `src/hdmi_exfil/sender/cli/console.py`
2. Create `src/hdmi_exfil/receiver/cli/console.py`
3. Add `hdmi-sender` and `hdmi-receiver` entry points to pyproject.toml

Tests: Add new tests for console flows (mock InquirerPy prompts).

### Step 12: Refactor CLI Functions for Console Delegation

Extract the pipeline logic from `send.py:main()` and `receive.py:main()` into callable functions that accept parameters directly (not via argparse). Both argparse `main()` and console can call these:

```python
# sender/cli/send.py

def run_send(
    input_path: str,
    mode: str = "sequential",
    profile_name: str = "speed",
    renderer: str = "pygame",
    fps: int | None = None,
    redundancy: int = 1,
    fountain_redundancy: float | None = None,
    screen: int = 0,
) -> None:
    """Execute the send pipeline. Called by both argparse main() and console."""
    ...

def main() -> None:
    """Argparse entry point."""
    args = _build_parser().parse_args()
    run_send(
        input_path=args.input_path,
        mode=args.mode,
        ...
    )
```

This is cleaner than manipulating `sys.argv` to fake argparse calls.

## Scalability Considerations

| Concern | Now (v1.0) | After Restructure (v1.1) | Future |
|---------|-----------|--------------------------|--------|
| Install size (receiver-only) | All deps (pygame, numba, etc.) | opencv + numba + numpy only | Same |
| Install size (sender-only) | All deps | All deps minus nothing (sender needs most) | Same |
| Adding new protocols | Edit protocols/__init__.py | Edit core/protocols/__init__.py | Same pattern |
| Adding new CLI commands | Add to cli/ | Add to sender/cli or receiver/cli as appropriate | Same pattern |
| Cross-package imports | N/A (flat) | Enforced by directory structure | import-linter CI check |
| Test isolation | Good | Better (can test core without hw deps) | Same |

## Integration Points Between New and Existing Code

### New Components

| Component | Type | Depends On | Depended On By |
|-----------|------|-----------|----------------|
| `sender/cli/console.py` | NEW | InquirerPy, sender.cli.send, sender.cli.calibrate, cli.benchmark, sender.display.monitors | Entry point `hdmi-sender` |
| `receiver/cli/console.py` | NEW | InquirerPy, receiver.cli.receive, cli.benchmark, receiver.capture.source | Entry point `hdmi-receiver` |
| `sender/cli/send.run_send()` | EXTRACTED | Same as current main() | console.py, main() |
| `receiver/cli/receive.run_receive()` | EXTRACTED | Same as current main() | console.py, main() |
| Backward-compat shim files | TEMPORARY | New module locations | Old import paths (tests) |

### Modified Components

| Component | Change | Risk |
|-----------|--------|------|
| All `__init__.py` files | New package structure | LOW -- mostly empty |
| `sequential.py`, `fountain.py` | Replace cv2.resize with np.repeat | MEDIUM -- verify pixel-exact output |
| `pyproject.toml` | Extras, find:packages, new entry points | MEDIUM -- packaging is fiddly |
| All source imports | Prefix changes | HIGH -- must update every file |
| All test imports | Prefix changes | HIGH -- must update every test |

### Unchanged Components (Zero Modification)

| Component | Why Unchanged |
|-----------|--------------|
| `config.py` internal logic | Only import path changes |
| `prng.py` internal logic | Only import path changes |
| All protocol encode/decode logic | Only import path + cv2.resize change |
| `sampler.py` | Only import path changes |
| `metadata.py`, `reader.py`, `writer.py` | Only import path changes |
| `constants.json` | No change |
| `sender.html` | No change |
| Test logic | Only import paths change |

## Sources

- Direct codebase analysis of all 26 Python source files -- HIGH confidence
- Python Packaging User Guide: optional dependencies -- HIGH confidence (well-established setuptools feature)
- InquirerPy library (prompt_toolkit-based interactive prompts) -- MEDIUM confidence (from training data, not verified against current docs; API may have minor differences)
- setuptools `find:` packages -- HIGH confidence (standard feature)
- numpy `np.repeat` as cv2.INTER_NEAREST equivalent -- HIGH confidence (mathematically identical for integer scale factors on integer grids)

---

*Architecture research for v1.1: 2026-03-02*
