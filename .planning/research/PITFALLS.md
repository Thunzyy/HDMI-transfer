# Domain Pitfalls

**Domain:** Interactive CLI console addition + monorepo restructure with pip extras
**Project:** HDMI_exfil v1.1 -- Console Interactive & Restructure
**Researched:** 2026-03-02
**Supersedes:** Previous pitfalls research (2026-02-16) focused on v1.0 encoding domain

---

## Critical Pitfalls

Mistakes that break the existing ~300 tests, corrupt the import graph, or require reverts.

---

### Pitfall 1: Package-Dir Remapping Breaks All Existing Imports

**What goes wrong:** The current `pyproject.toml` maps `hdmi_exfil = "src"` via `[tool.setuptools.package-dir]`. This means `src/` IS the `hdmi_exfil` package -- `src/__init__.py` is `hdmi_exfil/__init__.py`, `src/protocols/fountain.py` is `hdmi_exfil.protocols.fountain`, etc. All ~300 tests import from `hdmi_exfil.*` using this mapping.

When restructuring to `src/core/`, `src/sender/`, `src/receiver/`, the natural instinct is to create:
```
src/
  core/        -> hdmi_exfil.core.*
  sender/      -> hdmi_exfil.sender.*
  receiver/    -> hdmi_exfil.receiver.*
```

But the current `package-dir` mapping means `src/core/` maps to `hdmi_exfil.core.*` ONLY if the packages list is updated correctly. The real trap is: if you move `src/protocols/` to `src/core/protocols/`, every single test that does `from hdmi_exfil.protocols.fountain import FountainDecoder` breaks instantly. That is 10+ test files, 40+ import lines.

**Why it happens:** The `package-dir` mapping in setuptools is a flat namespace override -- it does not support nested remapping. You cannot map `hdmi_exfil.core = "src/core"` AND `hdmi_exfil = "src"` simultaneously; the second overrides the first. You must choose: either all subpackages live under the mapped root, or you use a completely different layout.

**Consequences:**
- `ModuleNotFoundError` in every test file on the first `pytest` run after restructure
- CI/CD goes red and stays red until every import path is updated
- If done in one massive commit, impossible to bisect which change broke what
- Editable installs (`pip install -e .`) may cache the old package mapping and silently use stale modules

**Warning signs:**
- `ImportError: No module named 'hdmi_exfil.protocols'` after moving files
- Tests pass locally (stale `.pyc` cache) but fail in CI (clean environment)
- `pip install -e .` completes but `import hdmi_exfil.core` fails

**Prevention:**
1. **Keep `hdmi_exfil.*` as the public import namespace.** Do NOT change what tests import. The internal file layout can change, but re-export everything from the original module paths using `__init__.py` re-exports.
2. **Create compatibility shims.** If `hdmi_exfil.protocols.fountain` moves to `hdmi_exfil.core.protocols.fountain`, keep a `src/protocols/__init__.py` that does `from hdmi_exfil.core.protocols.fountain import *` so old imports continue to work.
3. **Test the import graph FIRST.** Before moving any file, create a test that does `import hdmi_exfil.protocols.fountain; import hdmi_exfil.config; import hdmi_exfil.capture.sampler` etc. Run it after every file move.
4. **Move one subpackage at a time.** Move `protocols/` first, verify all tests pass, commit. Then `capture/`, verify, commit. Then `display/`, etc.
5. **Delete `__pycache__` directories and `.pyc` files** between each restructure step: `find . -type d -name __pycache__ -exec rm -rf {} +`
6. **Reinstall in editable mode** after each structural change: `pip install -e .` to refresh the package mapping.

**Detection:** Run `pytest --tb=short` after every file move. Any `ModuleNotFoundError` is this pitfall.

**Phase mapping:** Must be the FIRST structural change, with full test verification at each step.

**Confidence:** HIGH -- directly verified by reading `pyproject.toml` (line 41: `"hdmi_exfil" = "src"`) and all 40+ test import lines. The setuptools `package-dir` behavior is well-documented.

---

### Pitfall 2: Setuptools Package List Desync After Restructure

**What goes wrong:** The `pyproject.toml` explicitly lists all packages:

```toml
[tool.setuptools]
packages = [
    "hdmi_exfil",
    "hdmi_exfil.cli",
    "hdmi_exfil.capture",
    "hdmi_exfil.display",
    "hdmi_exfil.file_handling",
    "hdmi_exfil.protocols",
]
```

When you add new subpackages (`hdmi_exfil.core`, `hdmi_exfil.sender`, `hdmi_exfil.receiver`, etc.), you MUST add them to this list. Miss one, and that subpackage is silently excluded from the installed distribution. This is invisible in development (editable mode with `pip install -e .` uses the source tree directly) but breaks when someone installs from the sdist/wheel, or in CI with `pip install .`.

**Why it happens:** The explicit packages list is a legacy pattern from when auto-discovery was unreliable. It is safe but demands manual maintenance. The failure mode is particularly insidious because editable installs mask the problem -- you only discover it when building a distribution or installing in a fresh environment.

**Consequences:**
- `ModuleNotFoundError` when installing from sdist/wheel but not in development
- New modules work in editable mode but silently vanish from the distribution
- CI tests pass (editable install) but user installation breaks

**Prevention:**
1. **Switch to auto-discovery.** Replace the explicit packages list with:
   ```toml
   [tool.setuptools.packages.find]
   where = ["src"]
   ```
   This automatically finds all packages under `src/` that have `__init__.py`. Combined with `package-dir = {"" = "src"}` (note: change from the current `"hdmi_exfil" = "src"`), it handles any restructure automatically.

2. **If keeping explicit list:** Add a CI check that compares the listed packages against `find src -name __init__.py` and fails if they diverge.

3. **Test with `pip install .` (NOT `-e .`)** in CI to catch missing packages.

**Detection:** `pip install .` in a venv, then `python -c "from hdmi_exfil.core.protocols import fountain"` -- if this fails but `pip install -e .` works, you have this bug.

**Phase mapping:** Address at the very start of restructure, ideally by switching to auto-discovery first, before moving files.

**Confidence:** HIGH -- directly observed: the current `pyproject.toml` uses explicit package listing (lines 31-38). The auto-discovery vs explicit listing behavior is well-documented in setuptools docs.

---

### Pitfall 3: Entry Point Functions Move But pyproject.toml Stale References

**What goes wrong:** The current entry points are:

```toml
[project.scripts]
hdmi-send = "hdmi_exfil.cli.send:main"
hdmi-recv = "hdmi_exfil.cli.receive:main"
hdmi-calibrate = "hdmi_exfil.cli.calibrate:main"
hdmi-bench = "hdmi_exfil.cli.benchmark:main"
```

If the restructure moves CLI modules (e.g., `hdmi_exfil.cli.send` becomes `hdmi_exfil.sender.cli.send`, or the `main()` function is replaced by the new interactive console entry point), the entry point strings in `pyproject.toml` must be updated simultaneously. If they are not, `pip install` generates wrapper scripts that call non-existent module paths, and the `hdmi-send` / `hdmi-recv` commands fail with `ModuleNotFoundError` at invocation time -- not at install time.

**Why it happens:** Entry point resolution is lazy -- pip generates a wrapper script that does `from hdmi_exfil.cli.send import main; main()` at runtime. The install succeeds even if the module path is wrong; the error only surfaces when the user runs the command.

**Consequences:**
- `hdmi-send`, `hdmi-recv`, `hdmi-calibrate`, `hdmi-bench` all break silently
- Users who installed the package cannot use it (the error appears at runtime, not install time)
- If the new interactive console creates NEW entry points (e.g., `hdmi-console`), the old ones must still work or be explicitly deprecated

**Warning signs:**
- `ModuleNotFoundError: No module named 'hdmi_exfil.cli.send'` when running `hdmi-send`
- Package installs successfully but no console scripts work

**Prevention:**
1. **Add a smoke test** that imports every entry point function:
   ```python
   def test_entry_points_importable():
       from hdmi_exfil.cli.send import main as send_main
       from hdmi_exfil.cli.receive import main as recv_main
       from hdmi_exfil.cli.calibrate import main as cal_main
       from hdmi_exfil.cli.benchmark import main as bench_main
       assert callable(send_main)
       assert callable(recv_main)
       assert callable(cal_main)
       assert callable(bench_main)
   ```
2. **Keep existing entry points working.** If `hdmi_exfil.cli.send:main` is the old direct-mode entry point, keep it AND add a new `hdmi-sender-console` entry point for the interactive mode. Do not replace; add.
3. **Update entry points in the same commit** as the module move.
4. **After restructure, run:** `pip install -e . && hdmi-send --help` to verify each command.

**Phase mapping:** Must be verified after every file move that touches the `cli/` directory.

**Confidence:** HIGH -- directly observed: 4 entry points defined in pyproject.toml (lines 25-28), all pointing to `hdmi_exfil.cli.*:main`. Setuptools entry point lazy-loading behavior is well-documented.

---

### Pitfall 4: InquirerPy Maintenance Status and prompt_toolkit Compatibility

**What goes wrong:** InquirerPy (the planned interactive CLI library) depends on `prompt_toolkit >= 3.0.1`. The library's last PyPI release (0.3.4) was in 2022. The GitHub repository (kazhala/InquirerPy) has had minimal commit activity since 2023. `prompt_toolkit` itself is actively maintained (version 3.0.x), but there is a risk of incompatibility between InquirerPy's pinned dependency range and future prompt_toolkit releases.

More critically for this project: InquirerPy's `inquirer` module uses `prompt_toolkit`'s `Application` class, which takes control of the terminal's event loop. If the HDMI receiver is running OpenCV windows (`cv2.imshow`) or pygame in the same process, the terminal event loop and the GUI event loop will conflict, causing hangs or crashes.

**Why it happens:** InquirerPy is a wrapper around `prompt_toolkit`'s low-level prompt session, which runs its own event loop (asyncio-based). Libraries like OpenCV and pygame also run event loops (SDL event loop, HighGUI event loop). Two competing event loops in one process is a classic source of deadlocks.

**Consequences:**
- InquirerPy menu appears but keyboard input is swallowed by the OpenCV/pygame event loop
- Terminal cursor corruption after exiting an InquirerPy prompt when pygame was initialized
- On Windows specifically, `prompt_toolkit` uses Win32 console APIs that may conflict with pygame's SDL2 console mode
- If InquirerPy stops being maintained and a prompt_toolkit 4.x is released with breaking changes, the interactive CLI breaks with no upstream fix available

**Warning signs:**
- Arrow keys don't work in the menu (intercepted by OpenCV/pygame)
- Terminal renders garbage characters after exiting a menu
- `RuntimeError: This event loop is already running` errors
- Menu works fine in isolation but hangs when called between send/receive operations

**Prevention:**
1. **Architectural separation:** The interactive menu must run in a phase completely separate from any display/capture operation. Flow: menu collects all parameters -> menu exits completely -> display/capture begins. Never overlap InquirerPy prompts with OpenCV/pygame.
2. **Lazy-import pygame and cv2.** Do not import them at module level in the console entry point. Import them only when the user selects a send/receive action, after the InquirerPy session is fully closed.
3. **Pin InquirerPy version explicitly:** `InquirerPy>=0.3.4,<0.4` to avoid accidental upgrades to hypothetical incompatible releases.
4. **Have a fallback plan.** If InquirerPy becomes unmaintained, `questionary` (built on same `prompt_toolkit`, actively maintained as of 2025) is a near-drop-in replacement with identical arrow-key menu semantics.
5. **Test the menu in a real terminal**, not just in pytest (which captures stdin/stdout and masks event loop issues).

**Detection:** Run the interactive console, navigate menus, select "Send Python", verify pygame opens correctly. Then press ESC to return to the menu and verify the menu still works. This round-trip is the critical test.

**Phase mapping:** Must be validated in the first interactive CLI prototype, BEFORE building out all menu options.

**Confidence:** MEDIUM -- InquirerPy's maintenance status is based on training data (last release 2022, minimal activity 2023). The event loop conflict between prompt_toolkit and SDL2/OpenCV is a well-understood pattern but has not been verified specific to this project.

---

### Pitfall 5: Extras Dependencies That Import at Module Level Break Minimal Installs

**What goes wrong:** The plan is `pip install hdmi-exfil[sender]` installs pygame-ce + screeninfo (sender-only deps) and `pip install hdmi-exfil[receiver]` installs opencv-python (receiver-only dep). But the current code has cross-dependencies:

1. `hdmi_exfil.config` (shared) imports nothing exotic -- safe.
2. `hdmi_exfil.protocols.__init__` imports `SequentialProtocol` and `FountainProtocol` -- these import `numpy` (shared) and `struct` (stdlib) -- safe.
3. `hdmi_exfil.cli.send` imports `pygame-ce` (via `hdmi_exfil.display.renderer.PygameRenderer`) and `screeninfo` at module level.
4. `hdmi_exfil.cli.receive` imports `cv2` (opencv-python) at module level.
5. `hdmi_exfil.cli.benchmark` imports `hdmi_exfil.capture.sampler` which imports `numpy` -- safe. But `sample_frame` itself is shared between sender benchmark and receiver decode.

The trap: if `hdmi_exfil.protocols.__init__` is imported during `pip install hdmi-exfil[receiver]`, and it transitively imports something sender-only, the receiver-only installation breaks. Currently `protocols/__init__.py` imports cleanly, but any future change that adds a sender-only import to a shared module breaks the extras model.

More immediately: `hdmi_exfil.display.renderer` imports `cv2` at module level (line 23: `import cv2`). This module is used by the sender (`FrameRenderer`). If `cv2` (opencv-python) is listed as a receiver-only extra but `display.renderer` is imported by sender code, then `[sender]` install without `[receiver]` will ALSO fail because cv2 is missing.

**Why it happens:** Python's import system is eager -- `import cv2` at the top of a module file executes immediately when the module is first imported, regardless of whether the caller uses the cv2-dependent code path. The extras system only controls what pip installs; it cannot control what Python tries to import at runtime.

**Consequences:**
- `pip install hdmi-exfil[sender]` fails at runtime because `display.renderer` imports cv2
- `pip install hdmi-exfil[receiver]` fails at runtime because... actually receiver needs cv2, which is fine. But if receiver code ever imports `display.renderer.PygameRenderer` (which imports pygame), receiver-only install breaks.
- The entire extras model collapses into "just install everything" (`[all]`)

**Warning signs:**
- `ImportError: No module named 'cv2'` when running `hdmi-send`
- `ImportError: No module named 'pygame'` when running `hdmi-recv`
- Users give up on extras and use `pip install hdmi-exfil[all]`

**Prevention:**
1. **Audit every top-level import in every module.** Create an import dependency graph. Classify each dependency as `core`, `sender`, or `receiver`.
2. **Lazy-import expensive/optional dependencies.** `display.renderer` should NOT import `cv2` at module level. Instead:
   ```python
   class FrameRenderer:
       def __init__(self, ...):
           import cv2
           self._cv2 = cv2
           ...
   ```
3. **Split `display.renderer` into two files:** `display.renderer_cv2` (requires cv2) and `display.renderer_pygame` (requires pygame-ce). The sender imports only the pygame one; the receiver imports only the cv2 one (or neither if it only uses `cv2.imshow` directly).
4. **Dependency classification for extras:**
   - `core`: numpy, screeninfo (lightweight)
   - `sender`: pygame-ce, numba
   - `receiver`: opencv-python, numba
   - `all`: core + sender + receiver
5. **Add import-only tests for each extras profile:**
   ```python
   def test_core_imports_without_pygame():
       # Mock pygame as unavailable, verify core imports work
   ```

**Detection:** Create a clean venv, `pip install hdmi-exfil[sender]` (without `[receiver]`), then `python -c "from hdmi_exfil.cli.send import main"`. If this fails with `ImportError`, the extras split is broken.

**Phase mapping:** Must be resolved DURING the restructure, not after. The file-level split into core/sender/receiver must be driven by the dependency graph, not by functional grouping alone.

**Confidence:** HIGH -- directly verified: `display/renderer.py` line 23 imports `cv2` unconditionally. The eager-import behavior of Python is fundamental and well-documented.

---

### Pitfall 6: constants.json and importlib.resources Path Breaks During Restructure

**What goes wrong:** `config.py` loads `constants.json` using `importlib.resources`:

```python
_constants_path = files("hdmi_exfil").joinpath("constants.json")
```

This resolves to `src/constants.json` because `"hdmi_exfil" = "src"` in the package-dir mapping, and `pyproject.toml` declares `package-data = { hdmi_exfil = ["constants.json"] }`.

If the restructure changes the package-dir mapping or moves `constants.json` to a different location (e.g., `src/core/constants.json`), the `files("hdmi_exfil")` call will resolve to the wrong directory. `importlib.resources.files()` is sensitive to the exact package name and its location on disk.

**Why it happens:** `importlib.resources.files("hdmi_exfil")` resolves the package name to a filesystem path using the installed package metadata. If the package-dir mapping changes, or if `constants.json` moves to a subpackage, the path resolution changes. In editable mode, it may point to the source tree; in installed mode, it points to site-packages. These can diverge after restructuring.

**Consequences:**
- `FileNotFoundError` when importing `hdmi_exfil.config` -- this breaks EVERYTHING because every module depends on config
- Works in editable mode but fails in installed mode (or vice versa)
- The web sender template build (`sender.html` built from `constants.json`) may use a different copy than the Python code

**Warning signs:**
- `FileNotFoundError: constants.json` at import time
- Config values are different between the web sender and Python sender (if multiple copies of constants.json exist after restructure)

**Prevention:**
1. **Move constants.json with config.py.** Wherever `config.py` lives, `constants.json` must be in the same package directory.
2. **Update `package-data` in pyproject.toml** whenever constants.json moves:
   ```toml
   [tool.setuptools.package-data]
   "hdmi_exfil.core" = ["constants.json"]  # if moved to core/
   ```
3. **Update the `files()` call** to match:
   ```python
   _constants_path = files("hdmi_exfil.core").joinpath("constants.json")
   ```
4. **Add a test** that imports `hdmi_exfil.config` and verifies `WIDTH`, `HEIGHT`, `BLOCK_SIZE` are the expected values. This catches silent path resolution failures.
5. **Verify in both editable AND installed mode** after the move.

**Detection:** `python -c "from hdmi_exfil.config import WIDTH; print(WIDTH)"` -- should print `1920`.

**Phase mapping:** Must be handled in the same commit as any file move involving `config.py` or `constants.json`.

**Confidence:** HIGH -- directly observed: `config.py` line 23 uses `files("hdmi_exfil")`, and `pyproject.toml` line 44 specifies `hdmi_exfil = ["constants.json"]`. Both must be updated atomically with any restructure.

---

## Moderate Pitfalls

Mistakes that cause delays, technical debt, or degraded developer experience.

---

### Pitfall 7: Interactive Menu Blocks Terminal When OpenCV/Pygame Crashes

**What goes wrong:** The interactive console flow is: menu -> user selects "Send Python" -> pygame starts fullscreen -> send completes -> return to menu. If pygame crashes or the HDMI transfer fails with an unhandled exception, the terminal is left in a corrupted state because:

1. InquirerPy/prompt_toolkit alters terminal settings (raw mode, alternate screen buffer)
2. pygame-ce alters display mode (fullscreen, resolution change)
3. If pygame crashes without calling `pygame.quit()`, the display may stay in fullscreen mode, making the terminal inaccessible
4. On Windows, `prompt_toolkit` may have changed the console code page or input mode

**Why it happens:** Both InquirerPy and pygame modify global terminal/display state. If either crashes, the cleanup code (context manager `__exit__`, atexit hooks) may not run, leaving the terminal in a non-interactive state.

**Consequences:**
- Terminal becomes unusable after a crash (no cursor, raw mode active, wrong resolution)
- User must close and reopen the terminal
- On Windows, the console window may be behind a stuck fullscreen pygame surface

**Prevention:**
1. **Wrap every display/capture operation in try/finally:**
   ```python
   try:
       with PygameRenderer(...) as renderer:
           do_send(...)
   finally:
       pygame.quit()  # belt-and-suspenders cleanup
   ```
2. **Register an `atexit` handler** that calls `pygame.quit()` and `cv2.destroyAllWindows()`.
3. **Never run InquirerPy prompts while pygame/cv2 windows are open.** Close all windows, release all resources, THEN show the menu.
4. **Add a keyboard interrupt handler** (Ctrl+C) that performs cleanup before re-raising.
5. **Test the crash recovery path:** Force-kill the sender mid-transfer and verify the terminal recovers.

**Phase mapping:** Must be built into the console architecture from day one. Not something to add later.

**Confidence:** HIGH -- pygame fullscreen recovery issues and prompt_toolkit terminal state corruption are well-documented in both projects' issue trackers.

---

### Pitfall 8: Test Suite Regression From Accidental Import Side Effects

**What goes wrong:** The current test suite uses `--import-mode=importlib` (pyproject.toml line 48). This mode is more strict than the default `prepend` mode: it does not add the test directory to `sys.path` and instead relies on the installed package. This means tests import from the installed `hdmi_exfil` package, not directly from the source tree.

During restructure, if the editable install becomes stale (e.g., you moved files but didn't re-run `pip install -e .`), tests will import from the OLD installed location (stale `.pth` file) while you're editing the NEW location. This causes confusing failures where your code changes don't seem to take effect, or tests import modules you've already deleted.

Additionally, several test files use import-time side effects:
- `test_calibration.py` imports `BenchmarkResult` and `run_benchmark` at function level (lazy imports inside test functions) -- this is safe.
- `test_pygame_renderer.py` imports `PygameRenderer` at function level -- safe.
- But `test_sequential.py`, `test_fountain.py`, `test_xor_ops.py` all import at module level -- these run at test collection time and will fail immediately if the import paths are broken.

**Why it happens:** `--import-mode=importlib` is the correct choice for avoiding accidental source-tree imports, but it means the package MUST be properly installed at all times during development. It creates a stricter contract between the source layout and the installed layout.

**Consequences:**
- Tests appear to pass/fail inconsistently (stale install vs fresh code)
- `pytest` crashes at collection time with `ImportError` before any tests run
- Developer wastes hours debugging "why doesn't my fix work" when the answer is "you need to re-run pip install -e ."

**Prevention:**
1. **Always re-run `pip install -e .`** after any file move or pyproject.toml change. Add this to the contributing guide.
2. **Add a conftest.py check** that verifies the installed package version matches the source:
   ```python
   import hdmi_exfil
   import importlib.metadata
   installed_version = importlib.metadata.version("hdmi-exfil")
   # At minimum, verify the package is importable
   ```
3. **Use a Makefile/script** that wraps `pytest` with a `pip install -e .` first:
   ```bash
   pip install -e . && pytest
   ```
4. **Clear `__pycache__`** directories when debugging import issues.

**Phase mapping:** Applicable throughout the entire restructure process. The conftest check should be added before restructuring begins.

**Confidence:** HIGH -- directly observed: `pyproject.toml` line 48 specifies `--import-mode=importlib`. The behavior of importlib import mode is documented in pytest docs.

---

### Pitfall 9: Extras Groups With Conflicting or Circular Dependencies

**What goes wrong:** The planned extras are `[sender]`, `[receiver]`, and `[all]`. Consider the dependency assignments:

- `numpy` -- needed by both sender AND receiver (core dep, not an extra)
- `numba` -- needed by both (fountain XOR acceleration in both encode and decode)
- `opencv-python` -- needed by receiver (capture) AND sender (FrameRenderer uses cv2)
- `pygame-ce` -- needed by sender only
- `screeninfo` -- needed by sender only
- `InquirerPy` -- needed by both sender and receiver consoles

The problem: `opencv-python` is currently used by the sender too (FrameRenderer). If it is classified as receiver-only, sender-only install breaks. If it is classified as core, then the extras split provides less value. Similarly, `numba` is used by sender (XOR encode acceleration) AND receiver (XOR decode acceleration) -- it should be core, not an extra.

Additionally, `opencv-python` and `opencv-python-headless` are mutually exclusive on PyPI but have the same import name (`cv2`). If someone has `opencv-python-headless` installed and you depend on `opencv-python`, pip may install both and create a broken state, or refuse to resolve dependencies.

**Why it happens:** The project was built as a monolith where all dependencies are available everywhere. Retroactively splitting into extras requires untangling the actual dependency graph, which rarely matches functional boundaries (sender/receiver) cleanly.

**Consequences:**
- Extras that don't actually save any dependencies (everything ends up in core)
- Conflicting opencv variants causing `ImportError` or wrong build (no GUI support in headless)
- Users confused about which extras to install

**Prevention:**
1. **Map actual imports, not functional roles.** Use `pipdeptree` or manual analysis to determine which modules import which dependencies.
2. **Be honest about the split.** If the real dependency graph is:
   - Core: numpy, numba, InquirerPy
   - Sender extras: pygame-ce, screeninfo
   - Receiver extras: opencv-python
   Then the extras only save ~2 packages for receiver-only install and ~1 package for sender-only install. That may be acceptable -- document it.
3. **Refactor display/renderer.py** to remove the cv2 dependency from the sender path. The sender should use ONLY PygameRenderer. FrameRenderer (cv2-based) is legacy and can be receiver-only or removed entirely.
4. **Use `opencv-python` (not `-headless`)** as the dependency name and document that headless won't work (receiver needs `cv2.imshow` for the debug window).
5. **Test each extras profile in isolation** in CI with separate venvs.

**Phase mapping:** Dependency graph analysis must happen BEFORE the restructure, as it determines what moves where.

**Confidence:** HIGH -- directly observed: `display/renderer.py` imports cv2 at module level, and `cli/send.py` imports `FrameRenderer` and `PygameRenderer` from it. The opencv-python/headless conflict is well-documented on PyPI.

---

### Pitfall 10: InquirerPy on Windows -- Raw Mode and ANSI Escape Issues

**What goes wrong:** InquirerPy uses `prompt_toolkit`, which relies on ANSI escape sequences for cursor movement, color, and arrow-key navigation. On Windows, the behavior depends on the terminal:

- **Windows Terminal (wt.exe):** Full ANSI support. Works correctly.
- **cmd.exe:** Limited ANSI support (only with VT processing enabled via `SetConsoleMode`). `prompt_toolkit` enables this automatically, but if the console mode change fails (e.g., redirected stdout), menus render garbage characters.
- **PowerShell ISE:** Does NOT support VT sequences. Menus are completely broken.
- **Git Bash / MSYS2:** Uses mintty, which has its own terminal emulation. `prompt_toolkit` detects this as a "dumb terminal" and may fall back to basic input mode (no arrow keys, no colors).
- **SSH sessions / VSCode terminal:** Generally work but may have issues with terminal size detection.

Since this project targets Windows (Elgato 4K X + Windows is the primary platform), this is not a theoretical concern.

**Why it happens:** Windows terminal emulation has been fragmented for decades. `prompt_toolkit` handles most cases via the `win32` input/output backends, but edge cases remain. InquirerPy does not add a compatibility layer on top of `prompt_toolkit` -- it inherits all of its platform quirks.

**Consequences:**
- Menu renders as garbled text in some terminals
- Arrow keys don't work (user cannot navigate the menu)
- Colors don't display (menu is unreadable)
- Menu works in developer's terminal but fails in user's terminal

**Warning signs:**
- `[?25l` and other escape sequences printed as literal text
- Menu items displayed but arrow keys do nothing
- `UnicodeEncodeError` when rendering menu items with special characters

**Prevention:**
1. **Document required terminal:** "Use Windows Terminal (wt.exe) for best experience."
2. **Add a terminal capability check** at console startup:
   ```python
   import sys
   if sys.platform == 'win32' and not sys.stdout.isatty():
       print("Error: interactive console requires a real terminal.")
       sys.exit(1)
   ```
3. **Provide a `--no-interactive` fallback** that uses the existing argparse-based CLI for terminals that don't support InquirerPy.
4. **Test in multiple Windows terminals** during development: Windows Terminal, cmd.exe, PowerShell, Git Bash.
5. **Catch `prompt_toolkit` exceptions** at menu initialization and fall back gracefully:
   ```python
   try:
       from InquirerPy import inquirer
       result = inquirer.select(message="Choose action:", choices=[...]).execute()
   except Exception:
       # Fall back to simple numbered menu
       result = _simple_menu(choices)
   ```

**Phase mapping:** Must be validated in the first interactive CLI prototype. Build the fallback mechanism before building all menu options.

**Confidence:** MEDIUM -- Windows terminal fragmentation is well-known. The specific interaction between `prompt_toolkit` and each Windows terminal variant is based on training data and general knowledge, not verified against InquirerPy's current version specifically.

---

### Pitfall 11: Monorepo Extras Don't Prevent Cross-Boundary Imports at Runtime

**What goes wrong:** Pip extras are a dependency management mechanism, not an access control mechanism. Even if `hdmi-exfil[sender]` does not install `opencv-python`, nothing prevents Python code in the sender package from importing `cv2` if it happens to be installed for another reason. Similarly, nothing prevents a developer from adding `from hdmi_exfil.receiver.some_module import something` in a sender module.

Over time, cross-boundary imports creep in because Python does not enforce package boundaries. The extras split gradually becomes meaningless as code evolves.

**Why it happens:** Python has no concept of module visibility or package-level access control. Any installed module can import any other installed module. The extras split exists only in pyproject.toml metadata -- it is not enforced at runtime.

**Consequences:**
- Extras boundaries erode over time
- "Works on my machine" because the developer has all extras installed
- Clean installs fail because of undeclared cross-boundary dependencies

**Prevention:**
1. **Add a CI job that tests each extras profile in isolation:**
   ```bash
   # Test sender-only
   pip install .[sender,dev]
   pytest tests/test_sender_*.py

   # Test receiver-only
   pip install .[receiver,dev]
   pytest tests/test_receiver_*.py

   # Test core-only
   pip install .[dev]
   pytest tests/test_core_*.py
   ```
2. **Use an import linter** like `import-linter` or a custom check that verifies modules in `sender/` never import from `receiver/` and vice versa.
3. **Document the boundary** in the architecture docs and CLAUDE.md for the project.
4. **Organize tests by extras group** so each test file only tests code from one group.

**Phase mapping:** Set up the CI isolation tests during the restructure phase. The import linter can be added later but should be planned for.

**Confidence:** HIGH -- this is a well-known limitation of Python's module system. No specific tooling verification needed.

---

### Pitfall 12: New Interactive Console Doubles the Number of Entry Points to Maintain

**What goes wrong:** The current 4 entry points (`hdmi-send`, `hdmi-recv`, `hdmi-calibrate`, `hdmi-bench`) are standalone CLI commands with argparse. The new interactive console adds 2 more (`hdmi-sender-console`, `hdmi-receiver-console` or similar). But the existing entry points must continue to work for:
- Scripting and automation (CI, scheduled transfers)
- Users who don't want interactive menus
- Backward compatibility with existing documentation and workflows

This means every action in the interactive menu (send, calibrate, benchmark, etc.) must be implementable both as an interactive menu option AND as a standalone CLI command. If the logic is duplicated, they will drift apart. If the logic is shared, the shared code must handle both "I have all parameters from argparse" and "I need to ask the user interactively."

**Why it happens:** Adding an interactive layer on top of an existing CLI without planning the abstraction creates a dual-code-path maintenance burden.

**Consequences:**
- Bug fixes applied to the CLI path but not the console path (or vice versa)
- Interactive console prompts for parameters that the CLI already has defaults for
- Different behavior between `hdmi-send photo.png --mode fountain` and selecting "Send Python" from the console menu

**Prevention:**
1. **Single implementation, two entry points.** The interactive console collects parameters and builds the same `argparse.Namespace` (or equivalent config object) that the CLI command uses, then calls the same underlying function.
2. **Extract core logic from `main()` functions.** Each CLI entry point currently has a `main()` that parses args AND runs the operation. Split into `parse_args() -> Namespace` and `run(config) -> None`. The interactive console calls `run(config)` directly with parameters collected from the menu.
3. **Keep existing entry points unchanged.** The `hdmi-send` command should continue to work exactly as before. The console is an ADDITIONAL entry point, not a replacement.
4. **Test both paths** with the same test cases:
   ```python
   @pytest.mark.parametrize("entry", ["cli", "console"])
   def test_send_benchmark(entry):
       ...
   ```

**Phase mapping:** This architectural pattern must be established before building the interactive console. Refactor existing `main()` functions first.

**Confidence:** HIGH -- directly observed: all 4 `main()` functions in `cli/*.py` mix argument parsing with execution logic. This is a common pattern in CLIs that later need interactive wrappers.

---

## Minor Pitfalls

Mistakes that cause annoyance, confusion, or minor bugs.

---

### Pitfall 13: `pip install -e .` Editable Installs and Package Discovery Caching

**What goes wrong:** During active restructuring, developers run `pip install -e .` frequently. On Windows, pip's editable installs create a `.pth` file in site-packages that points to the source tree. If the package structure changes (new directories, renamed packages), the `.pth` file may point to stale paths. Additionally, Python caches the package `__path__` at first import, so even after re-running `pip install -e .`, a running Python process (or pytest session) may use cached stale paths.

**Prevention:**
1. Always start a fresh pytest session after `pip install -e .`
2. Delete `build/`, `*.egg-info/`, and `__pycache__/` before reinstalling
3. Consider using `pip install -e . --no-build-isolation` for faster iteration

**Phase mapping:** Minor -- just a development workflow annoyance during restructure.

**Confidence:** HIGH -- standard pip behavior.

---

### Pitfall 14: InquirerPy Prompt Reuse / Repeated Menu Bug

**What goes wrong:** The interactive console is a loop: show menu -> user picks action -> execute action -> show menu again. InquirerPy's `inquirer.select()` creates a new `prompt_toolkit` Application each time. On some platforms (particularly Windows), rapidly creating and destroying prompt_toolkit Applications can cause resource leaks (file handles, console mode state). After many iterations (e.g., user runs calibrate 10 times), the menu may become sluggish or stop responding.

**Prevention:**
1. Create the menu prompt once and re-execute it in a loop, rather than recreating it each iteration.
2. If InquirerPy does not support prompt reuse, add periodic cleanup (e.g., garbage collection) between menu iterations.
3. Monitor resource usage during long interactive sessions.

**Phase mapping:** Low priority -- only matters for extended interactive sessions.

**Confidence:** LOW -- based on general knowledge of prompt_toolkit resource management. Not verified with InquirerPy specifically. Flag for validation during implementation.

---

### Pitfall 15: sender.html Web Sender Template and constants.json Injection Path

**What goes wrong:** The web sender (`sender.html`) is built from `web/sender.template.html` with `constants.json` injected. If the restructure moves `constants.json` to a different location (e.g., `src/core/constants.json`), the build script for `sender.html` must be updated to find it. If it is not, `sender.html` will be built with the wrong constants (or fail to build), and the web sender will use different encoding parameters than the Python sender.

**Prevention:**
1. Keep `constants.json` in a well-known, documented location
2. If it moves, update all build scripts that reference it
3. Add a test that verifies the built `sender.html` contains the same constants as `hdmi_exfil.config`

**Phase mapping:** Check during any restructure step that moves constants.json.

**Confidence:** HIGH -- directly observed: `sender.html` exists alongside `web/sender.template.html`, and `config.py` loads from `files("hdmi_exfil").joinpath("constants.json")`.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| **Pre-restructure setup** | Stale editable install masks import errors (Pitfall 8) | Add conftest.py import verification, document `pip install -e .` workflow |
| **Package-dir change** | All imports break simultaneously (Pitfall 1) | Keep `hdmi_exfil.*` namespace, use `__init__.py` re-exports for backward compat |
| **Package list update** | New subpackages missing from distribution (Pitfall 2) | Switch to auto-discovery before restructuring |
| **Entry point update** | CLI commands break silently (Pitfall 3) | Smoke test that imports all entry point functions |
| **Dependency split** | Module-level imports defeat extras isolation (Pitfall 5) | Lazy-import pygame/cv2, split renderer file |
| **Dependency split** | opencv-python in sender path (Pitfall 9) | Remove FrameRenderer cv2 dep from sender, make pygame-only |
| **constants.json move** | FileNotFoundError crashes everything (Pitfall 6) | Move atomically with config.py, update package-data |
| **Interactive CLI prototype** | Event loop conflict with pygame/cv2 (Pitfall 4) | Menu phase and display phase must be completely separate |
| **Interactive CLI prototype** | Terminal corruption on crash (Pitfall 7) | try/finally cleanup, atexit hooks |
| **Interactive CLI prototype** | Windows terminal incompatibility (Pitfall 10) | Test in multiple terminals, provide `--no-interactive` fallback |
| **Console architecture** | Dual code paths drift apart (Pitfall 12) | Extract core logic from main(), single implementation |
| **Extras CI** | Cross-boundary imports undetected (Pitfall 11) | CI tests each extras profile in isolation |
| **Web sender** | constants.json path change breaks template build (Pitfall 15) | Update build script, add cross-validation test |

---

## Recommended Restructure Sequence (Risk-Minimizing Order)

Based on the pitfall analysis, the safest order for the v1.1 milestone is:

1. **Add import smoke tests** (tests all current `hdmi_exfil.*` imports work) -- catches regressions from step 2+
2. **Switch to auto-discovery** in pyproject.toml -- eliminates Pitfall 2 before it can occur
3. **Refactor `display/renderer.py`** to lazy-import cv2 and split renderers -- prerequisite for Pitfall 5/9
4. **Extract core logic from `main()` functions** -- prerequisite for Pitfall 12
5. **Move files incrementally** (one subpackage per commit, test after each) -- manages Pitfall 1
6. **Update entry points and package-data** atomically with each move -- manages Pitfall 3/6
7. **Add InquirerPy interactive console** (after restructure is stable) -- addresses Pitfall 4/7/10
8. **Define extras groups** and test in CI -- addresses Pitfall 5/9/11

---

## Sources

### HIGH Confidence (Direct Code Analysis)
- `pyproject.toml` package-dir mapping: line 41, `"hdmi_exfil" = "src"`
- `pyproject.toml` explicit package list: lines 31-38
- `pyproject.toml` entry points: lines 25-28
- `pyproject.toml` importlib import mode: line 48
- `config.py` importlib.resources usage: line 23, `files("hdmi_exfil").joinpath("constants.json")`
- `display/renderer.py` unconditional cv2 import: line 23, `import cv2`
- All 40+ test import lines verified via grep of `tests/` directory
- `conftest.py` configuration: hardware marker support

### MEDIUM Confidence (Training Data + General Knowledge)
- InquirerPy maintenance status (last release ~2022, based on training data)
- prompt_toolkit / pygame event loop conflicts (well-known pattern, not verified for this specific combination)
- Windows terminal ANSI escape sequence support (well-documented, not tested with InquirerPy specifically)
- setuptools auto-discovery behavior (documented in setuptools docs, not verified against latest version)

### LOW Confidence (Needs Validation)
- InquirerPy prompt reuse / resource leak behavior (Pitfall 14) -- theoretical, needs testing
- `questionary` as InquirerPy fallback (based on training data, should verify current maintenance status)
- prompt_toolkit 4.x compatibility risk (speculative -- no evidence of a 4.x release planned)
