# Phase 8: Interactive Sender Console - Research

**Researched:** 2026-03-02
**Status:** Complete
**Confidence:** HIGH (codebase fully explored, stack decision from prior research)

## Phase Boundary

**Goal:** Users can operate the sender through an interactive arrow-key menu instead of memorizing CLI flags -- the menu collects all parameters and delegates to the existing send pipeline.

**Requirements:** SEND-01 through SEND-08

## 1. Library Choice: InquirerPy

Already decided in `.planning/research/STACK.md`. InquirerPy (>=0.3.4) is the chosen library for interactive prompts. Built on prompt_toolkit, cross-platform (Windows + Linux + macOS), supports arrow-key list selection, file path prompts with completion, and Separator objects for menu grouping.

**Installation:** Add `"InquirerPy >= 0.3.4"` to the `sender` extras in `pyproject.toml`.

## 2. Existing Architecture Analysis

### Current Entry Points (pyproject.toml)

| Command | Module | Purpose |
|---------|--------|---------|
| `hdmi-send` | `hdmi_exfil.cli.send:main` | Argparse-driven file send (shim -> `sender.cli.send`) |
| `hdmi-calibrate` | `hdmi_exfil.cli.calibrate:main` | Calibrate subcommands (shim -> `receiver.cli.calibrate`) |
| `hdmi-bench` | `hdmi_exfil.cli.benchmark:main` | Benchmark throughput (shim -> `core.cli.benchmark`) |

### Functions to Delegate To

The interactive console must NOT duplicate logic. It must build the right parameters and call existing functions:

1. **Send file (Python):** `sender.cli.send` -- currently `main()` parses args and wires up protocol + renderer. Need to extract the send logic into a callable function that accepts parameters directly (not argparse).
2. **Send file (Browser):** Open the browser sender HTML. The `sender.html` file exists but has no CLI entry point currently. Simple `webbrowser.open()` call.
3. **Calibrate:** `receiver.cli.calibrate._cmd_send()` -- displays calibration pattern. Takes `profile` and `args` namespace.
4. **Detect hardware:** `sender.display.monitors.get_monitors()` -- already a clean function returning list of monitor dicts.
5. **Benchmark:** `core.cli.benchmark.run_benchmark()` -- already a clean function taking `profile`, `mode`, `payload_size_kb`, `duration_sec` and returning `BenchmarkResult`.

### Key Refactoring Needed: Extract `run_send()` from `send.py`

The current `sender.cli.send.main()` is monolithic -- it parses args, resolves profile, reads input, detects monitors, creates renderer, and runs the send loop all in one function. The interactive console needs to call the send logic without argparse.

**Strategy:** Extract a `run_send(input_path, mode, profile, screen, renderer_type, redundancy, fountain_redundancy)` function from `main()`. The `main()` function becomes a thin wrapper: parse args -> call `run_send()`. The interactive console also calls `run_send()` with menu-selected parameters.

This is the cleanest approach and avoids duplicating any encoding or display logic (satisfying success criterion #5).

## 3. Menu Structure (SEND-02)

```
HDMI Sender Console
─────────────────────
> Send file (Python)
  Send file (Browser)
  ─────────────────
  Calibrate
  Detect hardware
  Benchmark
  ─────────────────
  Quit
```

Uses `inquirer.select()` with `Separator()` for visual grouping. Arrow keys navigate, Enter selects.

## 4. Parameter Collection Flow (SEND-03, SEND-04, SEND-05, SEND-06)

When user selects "Send file (Python)", the console collects parameters through a sequence of prompts:

### 4a. File Path (SEND-03)

```python
from InquirerPy import inquirer
path = inquirer.filepath(
    message="File to send:",
    validate=lambda p: os.path.isfile(p),
).execute()
```

InquirerPy's `filepath` prompt type provides tab-completion out of the box. It uses prompt_toolkit's file path completer which handles both Unix and Windows paths.

### 4b. Resolution Profile (SEND-04)

```python
profile_name = inquirer.select(
    message="Resolution profile:",
    choices=["speed (1080p@240fps)", "balanced (1080p@60fps)", "quality (4K@30fps)"],
).execute()
```

Maps back to `PROFILES` dict keys.

### 4c. Encoding Mode (SEND-05)

```python
mode = inquirer.select(
    message="Encoding mode:",
    choices=["sequential", "fountain"],
).execute()
```

### 4d. Target Monitor (SEND-06)

```python
monitors = get_monitors()
choices = [f"Monitor {i}: {m['width']}x{m['height']}" for i, m in enumerate(monitors)]
selection = inquirer.select(
    message="Target monitor:",
    choices=choices,
).execute()
```

Dynamically detects monitors using the existing `get_monitors()` function.

## 5. Menu Loop (SEND-07)

After any action completes, return to the main menu. Simple `while True` loop:

```python
def main():
    while True:
        action = inquirer.select(...).execute()
        if action == "Quit":
            break
        dispatch(action)
```

This satisfies SEND-07: after send/calibrate/benchmark/detect completes, user returns to menu.

## 6. Ctrl-C Handling (SEND-08)

**Critical concern from STATE.md:** "InquirerPy + pygame/cv2 event loop conflict must be validated empirically."

### The Conflict

When `PygameRenderer` is active, `pygame.init()` takes over the display and event loop. InquirerPy uses `prompt_toolkit` which uses a separate terminal input event loop. These should NOT conflict because:

1. InquirerPy runs BEFORE the send loop (collecting parameters in the terminal)
2. PygameRenderer runs DURING the send loop (fullscreen display)
3. They never run simultaneously

The menu collects all parameters, THEN the send function takes over with pygame. After send completes and pygame quits, control returns to the terminal for the menu again.

### Ctrl-C Strategy

Wrap the entire console in a try/except:

```python
def main():
    try:
        while True:
            action = inquirer.select(...).execute()
            if action == "Quit":
                break
            try:
                dispatch(action)
            except KeyboardInterrupt:
                print("\nAction cancelled.")
    except (KeyboardInterrupt, EOFError):
        print()  # clean exit, no traceback
```

InquirerPy raises `KeyboardInterrupt` on Ctrl-C during prompts. The outer handler catches it for a clean exit. The inner handler catches it during actions (send/calibrate/benchmark).

For pygame specifically, the `PygameRenderer.__exit__` already calls `pygame.quit()`, so the context manager cleanup handles pygame shutdown even on KeyboardInterrupt.

## 7. New File Location

```
src/hdmi_exfil/sender/cli/
    send.py           # existing (add run_send extraction)
    console.py        # NEW: interactive sender console
```

Entry point in `pyproject.toml`:
```toml
hdmi-sender = "hdmi_exfil.sender.cli.console:main"
```

Also add a backward-compat shim at `src/hdmi_exfil/cli/sender_console.py` following the existing shim pattern.

## 8. Dependency Changes

In `pyproject.toml`:

```toml
[project.optional-dependencies]
sender = [
    "pygame-ce >= 2.5.0",
    "screeninfo >= 0.8",
    "InquirerPy >= 0.3.4",
]
```

InquirerPy is added to `sender` extras only (receiver gets it in Phase 9).

## 9. Browser Sender Action

"Send file (Browser)" should locate and open `sender.html`. Current location needs discovery:

```python
import webbrowser
from importlib.resources import files

html_path = files("hdmi_exfil.sender").joinpath("sender.html")
webbrowser.open(str(html_path))
```

If `sender.html` is not packaged as a resource, fall back to opening the file from the repo root. This is a nice-to-have action -- if the HTML file isn't found, print a helpful message.

## 10. Testing Strategy

### Unit Tests (no hardware needed)

1. **Menu dispatch test:** Mock InquirerPy prompts, verify correct function is called with correct parameters.
2. **Parameter mapping test:** Verify profile name -> ResolutionProfile, mode string -> protocol, monitor index -> offsets.
3. **Ctrl-C test:** Verify KeyboardInterrupt during prompt doesn't produce traceback.
4. **run_send extraction test:** Call `run_send()` with known parameters and mock renderer, verify protocol and frames.

### Manual Tests (hardware needed)

1. Run `hdmi-sender`, navigate menu with arrow keys, select Quit.
2. Select "Send file (Python)", tab-complete a file path, select profile/mode/monitor, verify send works.
3. Press Ctrl-C during prompt, verify clean exit.
4. Press Ctrl-C during active send, verify clean exit (no pygame crash).
5. Complete a send, verify return to main menu.

## 11. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| InquirerPy + pygame event loop conflict | LOW | HIGH | They never run simultaneously. Menu runs in terminal, send runs in pygame. Sequential, not parallel. |
| InquirerPy version incompatibility | LOW | MEDIUM | Pin to >=0.3.4, test during implementation. |
| Ctrl-C during pygame leaves terminal in bad state | MEDIUM | MEDIUM | Ensure `PygameRenderer.__exit__()` always runs via context manager. Add explicit `pygame.quit()` in finally block. |
| `sender.html` not found for browser action | LOW | LOW | Graceful fallback: print location instructions instead of crashing. |
| Tab completion on Windows paths | LOW | LOW | prompt_toolkit handles Windows paths natively. Tested in IPython for years. |

## 12. Implementation Order

1. **Extract `run_send()`** from `sender.cli.send.main()` -- refactor, no new functionality
2. **Add InquirerPy dependency** to pyproject.toml sender extras
3. **Create `sender.cli.console.py`** with main menu, Quit, and Detect hardware (simplest actions)
4. **Wire "Send file (Python)"** with parameter collection flow
5. **Wire remaining actions** (Calibrate, Benchmark, Browser)
6. **Add `hdmi-sender` entry point** to pyproject.toml
7. **Add shim** at `cli/sender_console.py`
8. **Add Ctrl-C handling** throughout
9. **Test** end-to-end

## RESEARCH COMPLETE

---
*Phase: 08-interactive-sender-console*
*Research completed: 2026-03-02*
