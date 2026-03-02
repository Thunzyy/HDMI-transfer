# Technology Stack: v1.1 Interactive CLI & Monorepo Restructure

**Project:** HDMI Exfil
**Researched:** 2026-03-02
**Scope:** NEW additions only -- interactive menus and monorepo pip extras
**Confidence:** MEDIUM (training data, no live verification available)

## Existing Stack (DO NOT CHANGE)

These are validated and shipping. Listed for context only.

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.11+ | Runtime |
| numpy | >=1.24 | Array ops |
| opencv-python | >=4.0 | Capture |
| pygame-ce | >=2.5.0 | Sender display |
| numba | >=0.60.0 | JIT XOR |
| screeninfo | >=0.8 | Monitor detection |
| pytest | >=8.0 | Testing |
| hypothesis | >=6.0 | Property tests |

## New Stack Additions

### Interactive CLI: InquirerPy

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| InquirerPy | >=0.3.4 | Arrow-key interactive menus for sender/receiver consoles | Best Python prompt library for structured menu UX. Built on prompt_toolkit. Supports list, checkbox, confirm, input prompts with arrow-key navigation. Already identified in PROJECT.md as the chosen library. |

**Why InquirerPy over alternatives:**

| Criterion | InquirerPy | questionary | simple-term-menu | raw prompt_toolkit |
|-----------|-----------|-------------|------------------|--------------------|
| Arrow-key list menus | Yes, native | Yes, native | Yes, native | Manual build |
| Nested/hierarchical menus | Yes (action dispatch) | Limited | No | Manual build |
| Keybinding customization | Full (prompt_toolkit) | Limited | Moderate | Full |
| Async support | Yes | No | No | Yes |
| Separator/header in menus | Yes (built-in Separator) | No | No | Manual |
| Style/theming | Full prompt_toolkit styles | Basic | ANSI only | Full |
| Dependency weight | prompt_toolkit + pfzy | prompt_toolkit | Zero deps (stdlib only) | prompt_toolkit |
| Maintenance (as of 2025) | Active | Slower releases | Active | Active (core) |
| Windows terminal support | Good (via prompt_toolkit) | Good | Poor (POSIX-centric) | Good |

**Recommendation: InquirerPy.** It provides the richest menu UX with minimal code. The `list` prompt type is exactly what the sender/receiver consoles need -- arrow-key selection from a list of actions. It supports `Separator` objects for visual grouping (e.g., separating "Transfer" actions from "Tools" actions). Built on `prompt_toolkit` which handles Windows Console API and Unix terminal correctly.

**Why NOT questionary:** Functionally similar but fewer features. No `Separator` support in list prompts, no fuzzy search, less customizable keybindings. Both use prompt_toolkit under the hood, so dependency weight is identical. InquirerPy is the superset.

**Why NOT simple-term-menu:** Zero dependencies is appealing, but it has poor Windows terminal support (relies on POSIX termios). This project targets Windows (Elgato capture card, ctypes.windll in sender). Disqualified.

**Why NOT raw prompt_toolkit:** Too low-level for menu-style prompts. InquirerPy is a well-designed layer over prompt_toolkit that saves 50-100 lines of boilerplate per menu. No reason to reinvent it.

### InquirerPy Dependencies (Transitive)

| Library | Pulled By | Notes |
|---------|-----------|-------|
| prompt_toolkit | InquirerPy (required) | Terminal rendering engine. Already mature (v3.x). Handles Windows Console API, ANSI escape sequences, input event loops. |
| pfzy | InquirerPy (required) | Fuzzy matching for search-capable prompts. Tiny library, no further deps. |

**Total new dependency footprint:** 3 packages (InquirerPy + prompt_toolkit + pfzy). All pure Python, no C extensions, no build requirements.

### Integration Pattern

InquirerPy integrates with the existing CLI by wrapping the current `argparse`-based entry points. The interactive menu dispatches to the same functions that argparse currently calls.

```python
# src/cli/sender_console.py (new file)
from InquirerPy import inquirer
from InquirerPy.separator import Separator

def sender_menu() -> None:
    """Interactive sender console with arrow-key menu."""
    while True:
        action = inquirer.select(
            message="HDMI Sender Console",
            choices=[
                "Send file (Python)",
                "Send file (Web browser)",
                Separator(),
                "Calibrate display",
                "Detect monitors",
                "Benchmark throughput",
                Separator(),
                "Settings",
                "Exit",
            ],
            default="Send file (Python)",
        ).execute()

        if action == "Exit":
            break
        # dispatch to existing functions...
```

**Key integration points with existing code:**
- `send.py::main()` -- the argparse-based sender becomes the "Send file (Python)" action
- `receive.py::main()` -- becomes the "Receive file" action
- `calibrate.py::main()` -- becomes "Calibrate" action
- `benchmark.py::main()` -- becomes "Benchmark" action
- New console entry points (`hdmi-sender`, `hdmi-receiver`) wrap the interactive menus
- Old entry points (`hdmi-send`, `hdmi-recv`, etc.) remain as direct CLI commands

**Pattern: Interactive menu wraps argparse, does not replace it.**
The interactive console builds an `argparse.Namespace` object from user selections and passes it to the existing `main()` logic. This preserves both interfaces: scripting via `hdmi-send file.zip --mode fountain` and interactive via `hdmi-sender`.

## Monorepo with pip extras

### Current pyproject.toml Structure

```toml
[project]
dependencies = [
    "opencv-python >= 4.0",
    "numpy >= 1.24",
    "screeninfo >= 0.8",
    "pygame-ce >= 2.5.0",
    "numba >= 0.60.0",
]

[project.optional-dependencies]
dev = ["pytest >= 8.0", "hypothesis >= 6.0"]
```

### Proposed pyproject.toml Structure

```toml
[project]
name = "hdmi-exfil"
version = "1.1.0"
requires-python = ">= 3.11"

# Core: shared protocol, encoding, config -- minimal deps
dependencies = [
    "numpy >= 1.24",
    "numba >= 0.60.0",
]

[project.optional-dependencies]
# Sender: display, monitor detection, interactive console
sender = [
    "pygame-ce >= 2.5.0",
    "screeninfo >= 0.8",
    "InquirerPy >= 0.3.4",
]
# Receiver: capture card, interactive console
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
# Direct CLI commands (non-interactive, backward compat)
hdmi-send = "hdmi_exfil.cli.send:main"
hdmi-recv = "hdmi_exfil.cli.receive:main"
hdmi-calibrate = "hdmi_exfil.cli.calibrate:main"
hdmi-bench = "hdmi_exfil.cli.benchmark:main"
# Interactive consoles (new)
hdmi-sender = "hdmi_exfil.cli.sender_console:main"
hdmi-receiver = "hdmi_exfil.cli.receiver_console:main"
```

### Install Patterns

```bash
# Sender machine only (no opencv needed)
pip install hdmi-exfil[sender]

# Receiver machine only (no pygame needed)
pip install hdmi-exfil[receiver]

# Full install (both sender + receiver)
pip install hdmi-exfil[all]

# Development (everything + test tools)
pip install -e ".[dev]"
```

### Dependency Partitioning Rationale

| Package | Core | Sender | Receiver | Why |
|---------|------|--------|----------|-----|
| numpy | Yes | -- | -- | Protocol encoding/decoding needs array ops everywhere |
| numba | Yes | -- | -- | XOR acceleration used by both sender (fountain encode) and receiver (fountain decode) |
| pygame-ce | -- | Yes | -- | Only sender displays frames; receiver never renders |
| screeninfo | -- | Yes | -- | Only sender needs monitor detection |
| opencv-python | -- | -- | Yes | Only receiver captures from capture card |
| InquirerPy | -- | Yes | Yes | Both consoles need interactive menus |

**Why numpy and numba in core, not optional:** Both protocols (sequential and fountain) use numpy for bit packing and numba for XOR. If you install only `[receiver]`, you still need numpy+numba to decode frames. If you install only `[sender]`, you still need them to encode. They are core dependencies, not role-specific.

### Package Directory Structure (Post-Restructure)

```toml
[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-dir]
"" = "src"
```

The source tree moves from flat `src/` mapped as `hdmi_exfil` to a proper `src/hdmi_exfil/` layout:

```
src/
  hdmi_exfil/
    __init__.py
    config.py
    prng.py
    constants.json
    core/                 # Shared protocol + encoding
      __init__.py
      protocols/
      file_handling/
    sender/               # Sender-specific
      __init__.py
      display/
      cli/
        send.py
        sender_console.py
    receiver/             # Receiver-specific
      __init__.py
      capture/
      cli/
        receive.py
        receiver_console.py
    cli/                  # Shared CLI utilities
      __init__.py
      calibrate.py
      benchmark.py
      progress.py
```

**Important: Keep `setuptools` as build backend.** The existing pyproject.toml uses `setuptools >= 61.0` as the build backend. Do NOT switch to hatchling or flit for this milestone. The previous STACK.md mentioned hatchling, but the project already works with setuptools and `extras_require` is a native setuptools feature via `[project.optional-dependencies]` (PEP 621). Switching build backends is unnecessary churn.

### Self-Referencing Extras

The `all` and `dev` extras use self-referencing (`hdmi-exfil[sender]`), which is supported in setuptools >= 61.0 and pip >= 21.2. Since the project already requires setuptools >= 61.0, this works out of the box. No build system change needed.

## What NOT to Add

| Avoid | Why |
|-------|-----|
| click / typer | Overkill for wrapping argparse. The existing argparse CLI works fine. InquirerPy handles the interactive layer. Adding click would require rewriting all 4 existing CLI modules for zero benefit. |
| rich | Tempting for pretty output, but adds a heavy dependency (25+ transitive) for cosmetic improvement. The project uses simple `print()` and `sys.stdout.write()` which is fine for a transfer tool. If future milestones want progress bars, `rich` can be considered then. |
| textual | TUI framework for full terminal apps. Massive overkill -- we need a menu, not a dashboard. |
| blessed / curses | Low-level terminal manipulation. prompt_toolkit (via InquirerPy) handles this better and cross-platform. |
| hatchling / flit / pdm | Build backend migration. Unnecessary -- setuptools works, extras work, no reason to change. |
| poetry | Dependency manager migration. Unnecessary churn for this milestone. |

## Version Compatibility Notes

| Concern | Status | Notes |
|---------|--------|-------|
| InquirerPy + Python 3.11+ | Compatible | InquirerPy supports Python 3.7+. No known issues with 3.11-3.13. |
| prompt_toolkit 3.x + Windows | Compatible | prompt_toolkit 3.x uses Windows Console API for input and ANSI for output. Works on Windows Terminal, PowerShell, cmd.exe. |
| Self-referencing extras | Compatible | Requires setuptools >= 61.0 (already specified) and pip >= 21.2 (standard in Python 3.11+). |
| InquirerPy + numba | No conflict | InquirerPy is pure Python. No native extension conflicts. |
| opencv-python + pygame-ce | No conflict in `[all]` | Both can coexist. opencv-python-headless would avoid GUI backend conflicts, but the existing project uses `opencv-python` (non-headless) and it works. Do not change unless a conflict surfaces. |

## Installation

```bash
# New dependency only (InquirerPy)
pip install "InquirerPy>=0.3.4"

# Full dev install with extras
pip install -e ".[dev]"
```

## Confidence Assessment

| Claim | Confidence | Basis |
|-------|------------|-------|
| InquirerPy is the right choice over questionary | MEDIUM | Training data comparison. InquirerPy's Separator support and richer API are well-documented in its GitHub/docs. Could not verify latest release version live. |
| InquirerPy >=0.3.4 is the latest stable | LOW | Training data only. Last known version was 0.3.4 (2023). Library may have newer releases. Verify with `pip install InquirerPy` to get latest. |
| prompt_toolkit Windows support is solid | HIGH | prompt_toolkit is the foundation of the Python REPL (IPython, ptpython) and has been Windows-tested for years. |
| Self-referencing extras in setuptools >=61.0 | MEDIUM | PEP 621 + setuptools docs support this. Standard pattern but not live-verified. |
| Proposed package structure works with setuptools | MEDIUM | Standard `src/` layout with `find:` packages. Well-documented pattern but needs testing with the existing import paths. |
| InquirerPy has no native extensions | HIGH | Pure Python + prompt_toolkit (pure Python) + pfzy (pure Python). No C/Rust compilation needed. |

## Migration Risk

**LOW risk addition.** InquirerPy is a new optional dependency that only affects the new console entry points. The existing `hdmi-send`, `hdmi-recv`, `hdmi-calibrate`, and `hdmi-bench` commands are untouched. If InquirerPy breaks, only the interactive consoles fail -- all direct CLI commands continue to work.

**MEDIUM risk for monorepo restructure.** Moving files from `src/` flat layout to `src/hdmi_exfil/core|sender|receiver/` changes all import paths. Every `from hdmi_exfil.protocols import ...` becomes `from hdmi_exfil.core.protocols import ...`. This is a one-time migration but touches every file and every test. Must be done in a single commit with comprehensive test validation.

## Sources

- InquirerPy GitHub: https://github.com/kazhala/InquirerPy (training data, not live-verified)
- InquirerPy docs: https://inquirerpy.readthedocs.io/ (training data)
- questionary GitHub: https://github.com/tmbo/questionary (training data)
- simple-term-menu GitHub: https://github.com/IngoMeyer441/simple-term-menu (training data)
- prompt_toolkit docs: https://python-prompt-toolkit.readthedocs.io/ (training data)
- PEP 621 (pyproject.toml metadata): https://peps.python.org/pep-0621/ (training data)
- setuptools extras documentation: https://setuptools.pypa.io/en/latest/userguide/dependency_management.html (training data)

**NOTE:** All sources are from training data (knowledge cutoff May 2025). WebSearch, WebFetch, and Bash were unavailable during this research session. Version numbers and maintenance status should be verified before implementation. In particular, confirm `InquirerPy>=0.3.4` is still the latest on PyPI by running `pip index versions InquirerPy`.

---
*Stack research for: HDMI Exfil v1.1 Interactive CLI & Monorepo Restructure*
*Researched: 2026-03-02*
*Verification status: Training data only -- live verification unavailable*
