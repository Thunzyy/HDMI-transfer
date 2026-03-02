# Project Research Summary

**Project:** HDMI Exfil v1.1 — Interactive CLI & Monorepo Restructure
**Domain:** Developer tooling — CLI UX enhancement + Python packaging restructure
**Researched:** 2026-03-02
**Confidence:** MEDIUM-HIGH (architecture from direct codebase analysis; stack and features from training data)

## Executive Summary

HDMI Exfil v1.1 has two distinct but interdependent goals: restructuring the Python package into a proper monorepo with role-based pip extras (`[sender]`, `[receiver]`, `[all]`), and layering an InquirerPy-based interactive console on top of the existing argparse CLI. Both goals rest on the sound v1.0 foundation — a well-structured codebase with clean protocol abstractions, numba-accelerated XOR, and approximately 300 passing tests. The research confirms the architecture is achievable, but the sequencing is critical: the monorepo restructure carries HIGH execution risk and must complete first, with all tests green at every step, before the interactive console is built.

The recommended approach is incremental restructure driven by backward-compatibility shims: create the new directory structure, move files one subpackage at a time, add re-export shims at old locations so the test suite stays green throughout, then remove shims after all imports are updated. The most dangerous single step is the `package-dir` remapping in `pyproject.toml` — the current `"hdmi_exfil" = "src"` mapping must be replaced with `"" = "src"` plus auto-discovered packages, and this must happen atomically with creation of `src/hdmi_exfil/` as the actual package root. InquirerPy is the right choice for the interactive console: it is built on prompt_toolkit, handles Windows terminals correctly, and provides the exact arrow-key list prompts the project needs with minimal boilerplate and zero C extensions.

The key risks are package import graph corruption during restructure, the hidden `cv2.resize` call in the encoding protocols leaking opencv-python into what should be a core-only dependency (making the extras split hollow), and the InquirerPy event loop conflicting with pygame/OpenCV during the send/receive phase. All three are preventable with the mitigation strategies documented in PITFALLS.md. The interactive console must be purely additive — the existing `hdmi-send`, `hdmi-recv`, `hdmi-calibrate`, and `hdmi-bench` commands must survive the restructure completely unchanged.

## Key Findings

### Recommended Stack

The existing stack (Python 3.11+, numpy, numba, pygame-ce, opencv-python, screeninfo, pytest, hypothesis) is unchanged. The only new runtime dependency is **InquirerPy >= 0.3.4**, which brings prompt_toolkit and pfzy as transitive dependencies. All three are pure Python with no C extensions, making them safe to add without build complications.

InquirerPy is the correct choice over questionary (fewer features, no Separator support), simple-term-menu (POSIX-centric, poor Windows support), and raw prompt_toolkit (too low-level for menu-style prompts). The pattern is: the interactive menu collects parameters via InquirerPy prompts, then delegates to the exact same functions that the argparse CLI calls — no logic duplication. The build backend stays as setuptools; no migration to hatchling or flit is warranted.

**Core technologies:**
- **Python 3.11+**: Runtime — unchanged, required
- **numpy + numba**: Core deps for both sender and receiver — protocol encoding/decoding, XOR acceleration; must remain in base dependencies, not extras
- **InquirerPy >= 0.3.4**: Interactive CLI menus — best Windows-compatible arrow-key prompt library; pure Python, zero build requirements
- **pygame-ce >= 2.5.0**: Sender display — sender extra only; never needed by receiver
- **opencv-python >= 4.0**: Capture and frame rendering — receiver extra; must also be removed from sender's encode path (replace `cv2.resize` with `np.repeat`) to clean the extras split
- **screeninfo >= 0.8**: Monitor detection — sender extra only
- **setuptools >= 61.0**: Build backend — already in use; self-referencing extras (`all = ["hdmi-exfil[sender]", ...]`) work out of the box at this version

**Critical version note:** Verify the latest InquirerPy version on PyPI before implementing — training data shows 0.3.4 but the library may have newer releases. Run `pip index versions InquirerPy` to confirm.

### Expected Features

The feature research separates table stakes (the interactive console is broken without these) from differentiators (valued but not blocking) and identifies explicit anti-features to avoid.

**Must have (table stakes):**
- **Arrow-key navigation** (TS-1) — the defining feature of an interactive console; InquirerPy `inquirer.select()` provides this out of the box
- **Sender main menu with 6 actions** (TS-2): Send (Python), Send (Browser), Calibrate, Detect hardware, Benchmark, Settings
- **Receiver main menu with 5 actions** (TS-3): Receive file, Calibrate signal, Detect capture card, Last transfer stats, Settings
- **Interactive file picker** (TS-4) — InquirerPy `filepath` prompt with autocomplete
- **Profile and mode selection prompts** (TS-5, TS-6) — arrow-key selection from short option lists
- **Monitor/capture device selection** (TS-7) — enumerate detected hardware, allow arrow-key selection
- **Graceful Ctrl-C handling** (TS-8) — clean exit at any prompt via KeyboardInterrupt wrapping
- **Return to main menu after action** (TS-9) — while-True loop; this is what makes it a console, not a one-shot command
- **Visual separation between actions** (TS-10) — clear screen or separator before re-showing menu
- **pip extras** (TS-11): `[sender]`, `[receiver]`, `[all]`, `[dev]`
- **Clean module separation** (TS-12): `core/`, `sender/`, `receiver/` subpackages — highest-effort task in the milestone
- **Console entry points** (TS-13): `hdmi-sender` and `hdmi-receiver` alongside existing commands
- **Existing CLI commands unchanged** (TS-14) — hard requirement, non-negotiable

**Should have (differentiators):**
- **Settings persistence** (D-1) — JSON config at `~/.hdmi-exfil/config.json`; saves last profile/mode/screen selection across sessions
- **Confirm before send/receive** (D-3) — summary prompt before starting a transfer; prevents accidental sends with wrong settings
- **Colored output and status indicators** (D-6) — ANSI colors via InquirerPy styling; success/error/warning distinction
- **Web-launch integration** (D-7) — `webbrowser.open()` for the "Send File (Browser)" menu option; currently requires manual file open
- **Advanced settings submenu** (D-8) — nested submenu keeps main menu clean; exposes FPS override, redundancy, buffer size

**Defer (v2+):**
- **Live hardware status on menu header** (D-2) — adds startup latency; use on-demand "Detect Hardware" action instead for MVP
- **Fuzzy file path input** (D-5) — text input with filepath completion is sufficient for MVP
- **Transfer history database** — in-memory last-transfer stats is sufficient; no SQLite needed

**Explicit anti-features (do not build):**
- Full TUI framework (curses, textual, rich TUI) — InquirerPy is the right scope; transfers use cv2.imshow and pygame that are incompatible with a persistent TUI
- Async/concurrent menu updates during transfers — incompatible with cv2/pygame event loops
- Custom keybindings beyond arrow keys — creates a learning curve and conflicts with terminal shortcuts
- Plugin system for menu extensibility — single-purpose tool with a fixed set of operations

### Architecture Approach

The target architecture reorganizes the flat `src/` layout into `src/hdmi_exfil/` with three namespaces: `core/` (shared protocol, encoding, file handling — depends only on numpy and numba), `sender/` (display, sender CLI, interactive console — adds pygame-ce, screeninfo, InquirerPy), and `receiver/` (capture, receiver CLI, interactive console — adds opencv-python, InquirerPy). The existing `cli/` shared utilities (progress, benchmark) remain at `hdmi_exfil.cli`. The interactive console modules are thin orchestrators: they collect parameters via InquirerPy prompts and delegate to extracted `run_send()` / `run_receive()` functions that both argparse `main()` and the console call. The console never contains encoding, display, capture, or file handling logic.

**Major components:**
1. **`hdmi_exfil.core`** — Protocol implementations (sequential, fountain), XOR ops, file handling, config, PRNG; no hardware dependencies; importable with only numpy+numba
2. **`hdmi_exfil.sender`** — Display renderer (pygame-ce), monitor detection, calibration patterns, argparse send/calibrate CLIs, new interactive sender console (`sender/cli/console.py`)
3. **`hdmi_exfil.receiver`** — Capture source (opencv), threaded capture, FPS reporting, argparse receive CLI, new interactive receiver console (`receiver/cli/console.py`)
4. **`hdmi_exfil.cli`** — Shared utilities: ProgressTracker, benchmark CLI (uses core only, no hardware)
5. **Interactive consoles** — InquirerPy prompt loop, lazy-import all hardware libraries, delegate to `run_send()` / `run_receive()`; no business logic

**Critical design constraint:** `core/` must never import from `sender/` or `receiver/`. `sender/` and `receiver/` must never import from each other. Dependency direction is strictly inward toward `core/`. This is enforced structurally by the directory layout and validated by CI isolation tests on each extras profile.

**cv2-in-core problem (must resolve before extras split):** Both `sequential.py` and `fountain.py` currently use `cv2.resize()` for nearest-neighbour upscaling. This must be replaced with `np.repeat(np.repeat(grid, bs, axis=0), bs, axis=1)`. The output is mathematically identical for integer scale factors. Removing this cv2 call from core encoding is a PREREQUISITE for the extras split to be meaningful — without it, the sender extra silently requires opencv-python.

**Incremental build sequence (12 steps):**
1. Switch pyproject.toml to auto-discovery
2. Add import smoke tests for all current paths
3. Create new directory tree with `__init__.py` files (no code moved)
4-5. Move core modules (bottom-up) with shims
6. Move sender modules with shims
7. Move receiver modules with shims
8. Replace `cv2.resize` with `np.repeat` in protocols
9. Update pyproject.toml extras and entry points
10. Update all internal imports to new paths
11. Update test imports
12. Remove shims and verify clean installs for each extras profile

### Critical Pitfalls

The pitfalls research identified 6 critical pitfalls (project-breaking) and 6 moderate pitfalls (delay/debt-causing), sourced directly from codebase analysis with HIGH confidence.

1. **Package-dir remapping breaks all 300+ test imports simultaneously** (P1, CRITICAL) — The current `"hdmi_exfil" = "src"` mapping must be replaced with `"" = "src"` plus `src/hdmi_exfil/` as the actual package root. Every test import breaks if done without backward-compat shims. Prevention: create shims at all old import paths before moving files; move one subpackage per commit; run full pytest after each.

2. **Setuptools explicit package list desync** (P2, CRITICAL) — The current pyproject.toml explicitly lists all packages (lines 31-38); adding new subpackages without updating the list silently excludes them from distributions but not from editable installs — the failure is invisible in development and only surfaces in CI or user installations. Prevention: switch to `[tool.setuptools.packages.find]` auto-discovery as the very first pyproject.toml change.

3. **Entry point paths go stale after restructure** (P3, CRITICAL) — pip generates wrapper scripts lazily; a wrong module path installs successfully but fails at runtime when the user runs the command. The 4 existing entry points (`hdmi_exfil.cli.send:main`, etc.) will all break if CLI modules move without corresponding pyproject.toml updates. Prevention: add smoke tests that import all 4 entry point functions; update entry points atomically in the same commit as any CLI module move.

4. **Module-level imports defeat extras isolation** (P5, CRITICAL) — `display/renderer.py` imports `cv2` unconditionally at line 23. This means `pip install hdmi-exfil[sender]` fails at runtime because cv2 is not in the sender extra. Prevention: lazy-import cv2 inside class constructors; replace `cv2.resize` with `np.repeat` in protocol encoding; split renderer into pygame-only and cv2-fallback files.

5. **constants.json path breaks if config.py moves** (P6, CRITICAL) — `config.py` uses `files("hdmi_exfil").joinpath("constants.json")`; if `config.py` moves to `core/`, this call must update to `files("hdmi_exfil.core")` and `package-data` must update simultaneously. A stale path causes `FileNotFoundError` at import time, which breaks every module since all depend on config. Prevention: move config.py and constants.json atomically; update both the Python call and pyproject.toml in the same commit.

6. **InquirerPy event loop conflicts with pygame/OpenCV** (P4, CRITICAL) — prompt_toolkit and SDL2/OpenCV event loops cannot run concurrently in the same process; running an InquirerPy prompt while pygame is initialized causes input to be swallowed or terminal corruption. Prevention: the menu phase must be completely separate from the display/capture phase; lazy-import pygame and cv2 in the console module; close all hardware resources before showing the menu.

## Implications for Roadmap

The research points to a clear 5-phase structure driven by dependency ordering: the monorepo restructure must precede the interactive console, the restructure must proceed incrementally to keep tests green throughout, and the interactive console is purely additive after the restructure is stable. Each phase has a clear deliverable and a clear rationale for its position.

### Phase 1: Packaging Foundation

**Rationale:** The monorepo restructure (TS-12) is the highest-risk work item and has no dependencies on any new features. It must come first so that all subsequent work happens against the correct import paths, avoiding a double-migration. This phase eliminates Pitfalls 1, 2, 5, and 6 before they can affect later phases. Doing the restructure while the codebase is stable and fully tested is far safer than doing it after adding new code.

**Delivers:** Properly laid-out `src/hdmi_exfil/` package with `core/`, `sender/`, `receiver/` namespaces; all 300+ tests green throughout; pip extras (`[sender]`, `[receiver]`, `[all]`, `[dev]`) verified in clean venvs; no functional changes to any user-facing behavior.

**Addresses:** TS-12 (module separation), TS-11 (pip extras), TS-14 (existing CLIs unchanged)

**Avoids:** P1 (package-dir remapping), P2 (package list desync), P5 (module-level imports defeat extras), P6 (constants.json path)

**Sequence within phase:**
1. Switch to auto-discovery (`packages.find: where = ["src"]`) as the first change
2. Add import smoke tests for all current `hdmi_exfil.*` paths
3. Create `src/hdmi_exfil/` directory structure with empty `__init__.py` files
4. Move core modules bottom-up (config+prng, protocols, file_handling, core/capture/sampler) with shims
5. Move sender modules (display, sender CLI files) with shims
6. Move receiver modules (capture/source, capture/threaded, receiver CLI files) with shims
7. Replace `cv2.resize` with `np.repeat` in sequential.py and fountain.py
8. Update pyproject.toml: extras groups, updated entry point paths, package-data
9. Update all internal imports to new `hdmi_exfil.core.*`, `hdmi_exfil.sender.*`, `hdmi_exfil.receiver.*` paths
10. Update all test imports to new paths
11. Remove shims
12. Verify `pip install -e .[dev]` + full pytest green; then verify `pip install .[sender]` and `.[receiver]` in fresh venvs

### Phase 2: CLI Architecture Refactor

**Rationale:** Before building the interactive console, the existing `main()` functions must be split into `parse_args()` and `run()` callable functions so the console can delegate to `run()` without duplicating logic (Pitfall 12). This is a prerequisite for correct console architecture, not optional polish. Doing this while the restructure is freshly complete — before any new console code exists — minimizes the scope of the refactor.

**Delivers:** `run_send()`, `run_receive()`, `run_calibrate()`, `run_benchmark()` functions callable by both argparse and console; existing commands (`hdmi-send`, `hdmi-recv`, etc.) unchanged in behavior; `hdmi-sender` and `hdmi-receiver` entry points registered in pyproject.toml (pointing to new empty console stubs).

**Addresses:** TS-13 (console entry points), TS-14 (backward compat)

**Avoids:** P3 (stale entry points), P12 (dual code paths drift apart over time)

### Phase 3: Interactive Sender Console

**Rationale:** With the restructure stable and the CLI architecture correct, building the sender console is low-risk. All dependencies (InquirerPy, sender modules, `run_send()`) are in place. The sender console is built first because "Send file (Python)" is the primary user workflow, and the sender hardware (display) is easier to test than the receiver hardware (capture card enumeration).

**Delivers:** `hdmi-sender` interactive console with arrow-key menu (6 actions), file picker, profile/mode/monitor selection, confirm prompt, return-to-menu loop, Ctrl-C handling, screen clearing.

**Addresses:** TS-1, TS-2, TS-4, TS-5, TS-6, TS-7 (sender side), TS-8, TS-9, TS-10

**Avoids:** P4 (event loop conflict — lazy-import hardware libs, strict phase separation before/after menu), P7 (terminal corruption — try/finally `pygame.quit()`), P10 (Windows terminal — `sys.stdout.isatty()` check, fallback to simple numbered menu)

**First milestone within phase:** Build the menu -> send (pygame fullscreen) -> return to menu round-trip and validate it works in Windows Terminal before building any other menu options. If this round-trip fails, the architecture must change before proceeding.

### Phase 4: Interactive Receiver Console

**Rationale:** Same pattern as Phase 3 applied to the receiver. Separated into its own phase because the receiver has different hardware (capture card enumeration via OpenCV index probing, which is slower and more error-prone than monitor detection) and its own distinct UX flows.

**Delivers:** `hdmi-receiver` interactive console with receive, calibrate signal, detect capture card, last-transfer-stats, and settings actions.

**Addresses:** TS-1, TS-3, TS-7 (receiver side), TS-8, TS-9, TS-10

**Avoids:** P4, P7, P10 (same mitigations as Phase 3)

### Phase 5: UX Polish & Differentiators

**Rationale:** All table stakes are complete after Phase 4. This phase adds differentiators that improve the experience without architectural changes. Each item is independent and low-risk; they can be delivered in any order or across multiple minor releases.

**Delivers:** Settings persistence (D-1, JSON config), confirm-before-send prompt (D-3), colored output (D-6, ANSI via InquirerPy styling), web-launch integration (D-7, `webbrowser.open()`), advanced settings submenu (D-8).

**Addresses:** D-1, D-3, D-6, D-7, D-8

**Avoids:** AF-1 (full TUI), AF-2 (async menu updates), AF-8 (transfer history database)

### Phase Ordering Rationale

- Phase 1 must be first: it changes import paths for everything; doing it after adding console code means migrating new code too
- Phase 2 must precede Phases 3-4: the console delegation pattern requires extracted `run_*()` functions; building the console before this refactor forces logic duplication
- Phases 3 and 4 are logically independent (sender and receiver consoles do not interact) but sender first is the primary user workflow and is easier to test without capture hardware
- Phase 5 is purely additive; any item can be deferred or delivered incrementally without affecting the core milestone

### Research Flags

Phases likely needing validation during implementation (not full research, but empirical checks):

- **Phase 1 (Packaging Foundation):** The `cv2.INTER_NEAREST` to `np.repeat` pixel equivalence must be verified with an actual encode/decode round-trip test before removing the cv2 call. Also verify `pip install .[sender]` and `.[receiver]` in CI isolation environments — setuptools auto-discovery behavior should be confirmed against the actual installed setuptools version.
- **Phase 3 (Sender Console):** InquirerPy event loop isolation from pygame must be validated empirically in the first round-trip prototype before building out all menu options. Windows terminal compatibility (cmd.exe, PowerShell 5, Git Bash/mintty) needs explicit testing — not all terminals support ANSI sequences correctly with prompt_toolkit.

Phases with standard patterns (no additional research needed):

- **Phase 2 (CLI Refactor):** Standard extract-function refactoring; no new technology or integration risk.
- **Phase 4 (Receiver Console):** Same InquirerPy patterns validated in Phase 3; capture card enumeration is a simple OpenCV index probe.
- **Phase 5 (UX Polish):** All differentiators use stdlib or InquirerPy APIs already validated in Phase 3; JSON config file is trivial.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | InquirerPy version and maintenance status from training data only; verify latest on PyPI before implementing. prompt_toolkit Windows support is HIGH confidence based on its use as the Python REPL foundation (IPython, ptpython). |
| Features | MEDIUM-HIGH | Table stakes and anti-features are well-defined by the stated project goals. Feature ordering is driven by dependency analysis. Differentiator list is pragmatic and low-risk. |
| Architecture | HIGH | Based on direct codebase analysis of all 26 Python source files. Package-dir semantics, import paths, and component boundaries are verified facts, not inferences. The 12-step build sequence is derived from the actual dependency graph. |
| Pitfalls | HIGH (critical), MEDIUM (moderate) | Critical pitfalls verified by direct code inspection: renderer.py line 23 (unconditional cv2 import), config.py line 23 (files() call), pyproject.toml lines 25-48 (entry points, package list, import mode). Moderate pitfalls from well-documented Python/prompt_toolkit patterns. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **InquirerPy current version:** Training data shows 0.3.4; verify with `pip index versions InquirerPy` before pinning the requirement. Consider pinning as `InquirerPy>=0.3.4,<0.4` to avoid hypothetical breaking releases.
- **questionary as fallback:** If InquirerPy is found to be unmaintained (last release ~2022 per training data), questionary is the documented backup plan. Validate questionary's current maintenance status before starting Phase 3.
- **cv2.INTER_NEAREST vs np.repeat pixel equivalence:** The research asserts these are mathematically identical for integer scale factors on integer-valued grids. This must be verified with an actual encode/decode round-trip test as part of the Phase 1 migration step, not assumed.
- **Windows terminal compatibility matrix:** The interactive console's behavior on cmd.exe, PowerShell 5, and Git Bash/mintty must be validated empirically in Phase 3. The `--no-interactive` / numbered-menu fallback (Pitfall 10 mitigation) should be built before all menu options are complete, not after.
- **InquirerPy + pygame round-trip:** Menu -> send (pygame fullscreen) -> return to menu must be validated as the first milestone within Phase 3. If this specific round-trip fails, the architecture needs to change before building further.

## Sources

### Primary (HIGH confidence — direct codebase analysis)

- `pyproject.toml` (HDMI_exfil) — package-dir mapping (line 41), entry points (lines 25-28), explicit package list (lines 31-38), importlib import mode (line 48)
- `src/config.py` — importlib.resources usage: `files("hdmi_exfil").joinpath("constants.json")` (line 23)
- `src/display/renderer.py` — unconditional cv2 import at module level (line 23)
- All 26 Python source files — import graph, component boundaries, dependency classification
- All test files — 40+ import paths verified

### Secondary (MEDIUM confidence — training data, well-documented patterns)

- InquirerPy GitHub (kazhala/InquirerPy) — API, prompt types (select, filepath, confirm, fuzzy), Separator support
- InquirerPy docs (inquirerpy.readthedocs.io) — integration pattern, prompt_toolkit dependency
- PEP 621 + setuptools docs — `[project.optional-dependencies]`, self-referencing extras, auto-discovery
- prompt_toolkit docs — Windows Console API support, event loop behavior, Win32 input/output backends
- Python Packaging User Guide — pip extras, editable installs, importlib.resources

### Tertiary (LOW confidence — theoretical, needs empirical validation)

- InquirerPy prompt reuse resource leak behavior (Pitfall 14) — theoretical concern; needs testing during extended interactive sessions
- questionary as InquirerPy fallback — maintenance status should be verified before relying on this fallback plan
- prompt_toolkit 4.x compatibility risk — speculative; no evidence of a 4.x release being planned

---
*Research completed: 2026-03-02*
*Ready for roadmap: yes*
