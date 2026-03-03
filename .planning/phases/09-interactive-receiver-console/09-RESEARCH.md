# Phase 9: Interactive Receiver Console - Research

**Researched:** 2026-03-03
**Domain:** Interactive CLI console for HDMI receiver operations (InquirerPy + OpenCV capture)
**Confidence:** HIGH

## Summary

Phase 9 mirrors Phase 8 (Interactive Sender Console) on the receiver side. The pattern is fully established: InquirerPy arrow-key menus collect parameters, then delegate to existing receiver functions. The sender console (`src/hdmi_exfil/sender/cli/console.py`) provides the exact template -- dispatch dict, menu loop, nested Ctrl-C handling, and clean delegation to extracted `run_*` functions.

The primary refactoring need is extracting a `run_receive()` function from the monolithic `receive.py:main()`, exactly as `run_send()` was extracted in Phase 8 Plan 01. The current `main()` mixes argparse parsing, source opening, CaptureSource construction, ThreadedCapture wrapping, and mode dispatch into one 45-line function. The interactive console needs to call the receive logic without argparse. Additionally, InquirerPy must be added to the `receiver` extras in `pyproject.toml`.

The one genuinely new technical problem is capture device detection. OpenCV has no built-in "list devices" API. The simplest approach (probing indices 0 through a small range) is sufficient for this use case and avoids adding a new dependency. The `cv2-enumerate-cameras` library (v1.3.3, cross-platform) exists as an alternative but adds a dependency for marginal benefit in this tool's context.

**Primary recommendation:** Follow the Phase 8 pattern exactly. Plan 01 extracts `run_receive()` and adds InquirerPy to receiver extras. Plan 02 creates `receiver/cli/console.py` with the menu, device detection via index probing, and tests mirroring `test_sender_console.py`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RECV-01 | User can launch `hdmi-receiver` to get an interactive arrow-key menu | InquirerPy `inquirer.select()` with Separator -- identical to sender console pattern. Entry point `hdmi-receiver = "hdmi_exfil.receiver.cli.console:main"` in pyproject.toml. |
| RECV-02 | Receiver menu offers: Receive file, Calibrate signal, Detect capture card, Last transfer stats, Settings, Quit | 6 menu items using `inquirer.select()` with `Separator()` grouping. Dispatch dict maps each to a handler function. Settings and Last transfer stats are informational actions (print current config / last result). |
| RECV-03 | User can select capture device via arrow-key prompt with detected devices listed | Probe cv2.VideoCapture(0..9) to detect available devices. Display device index and resolution. Single-device case skips prompt (same UX pattern as sender single-monitor skip). |
| RECV-04 | User can select resolution profile (speed/balanced/quality) via arrow-key prompt | `inquirer.select()` over `PROFILES.keys()` with descriptive names -- identical to sender pattern. |
| RECV-05 | User can configure output directory via interactive prompt | `inquirer.text()` with default value `"received_files"`. Validate directory is writable or creatable. |
| RECV-06 | After any action completes, user returns to the main menu | `while True` loop with `_show_main_menu()` at top, break on Quit -- identical to sender pattern. |
| RECV-07 | Ctrl-C cleanly exits at any prompt without traceback | Nested try/except: inner catches during action (returns to menu), outer catches during prompt (exits cleanly) -- identical to sender pattern. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| InquirerPy | >= 0.3.4 | Arrow-key select menus, text prompts | Already used by sender console (Phase 8). Built on prompt_toolkit, cross-platform. |
| opencv-python | >= 4.0 | Video capture, device probing | Already a receiver dependency. Used for CaptureSource and frame processing. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| cv2-enumerate-cameras | 1.3.3 | Named device enumeration | NOT recommended for Phase 9 -- adds dependency for marginal UX gain. Index probing is sufficient. Revisit if users request device names. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Index probing (0..9) for device detection | cv2-enumerate-cameras library | Adds a dependency; provides device names but tool users typically have 1-2 capture cards and know the index. Probing is simpler and zero-dependency. |
| `inquirer.text()` for output directory | `inquirer.filepath()` | filepath provides auto-completion but validates as file, not directory. text() with a custom validator is cleaner for directory input. |

**Installation:**
```bash
# Add InquirerPy to receiver extras in pyproject.toml
# No new packages beyond what's already in the project
```

## Architecture Patterns

### Recommended Project Structure
```
src/hdmi_exfil/receiver/cli/
    receive.py        # existing (add run_receive extraction)
    console.py        # NEW: interactive receiver console
    __init__.py       # existing
src/hdmi_exfil/cli/
    receiver_console.py  # NEW: backward-compatible import shim
```

### Pattern 1: Extract run_receive() -- Mirror of Phase 8 run_send() Extraction

**What:** Extract core receive logic from `receive.py:main()` into a standalone `run_receive()` function with explicit parameters. `main()` becomes a thin argparse wrapper.

**When to use:** Before creating the interactive console. The console must call `run_receive()` without constructing argparse namespaces.

**Current main() analysis (lines 485-530):**
The current `main()` does these things in sequence:
1. Parse args (argparse)
2. Resolve profile from args
3. Parse source string to int (camera index) or keep as string (file path)
4. Construct CaptureSource with profile dimensions
5. Optionally wrap in ThreadedCapture
6. Call `_run_receiver(source, args, profile)` which dispatches on `args.mode`

**Key problem:** `_run_receiver()` currently takes an `argparse.Namespace` and reads `args.mode` and `args.output`. This must be changed to explicit parameters.

**Proposed run_receive() signature:**
```python
def run_receive(
    source: int | str,
    mode: str = "auto",
    profile: ResolutionProfile | None = None,
    output: str = "received_files",
    threaded: bool = True,
    buffer_size: int = 16,
) -> None:
    """Execute the full receive pipeline with explicit parameters."""
```

**main() becomes:**
```python
def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    run_receive(
        source=args.source,
        mode=args.mode,
        profile=PROFILES[args.profile] if args.profile else None,
        output=args.output,
        threaded=args.threaded,
        buffer_size=args.buffer_size,
    )
```

**CRITICAL:** The internal `_run_receiver()` helper must also stop depending on `args.mode` / `args.output`. Replace with explicit parameters. This is a small change -- just pass `mode` and `output` as arguments instead of reading from a Namespace.

### Pattern 2: Console Dispatch Dict -- Identical to Sender

**What:** Module-level `_DISPATCH` dictionary mapping menu strings to handler functions.

**Example (from sender console, verified working):**
```python
_DISPATCH = {
    _MENU_RECEIVE: _action_receive,
    _MENU_CALIBRATE: _action_calibrate,
    _MENU_DETECT: _action_detect,
    _MENU_STATS: _action_stats,
    _MENU_SETTINGS: _action_settings,
}

def main() -> None:
    try:
        while True:
            action = _show_main_menu()
            if action == _MENU_QUIT:
                break
            handler = _DISPATCH.get(action)
            if handler is None:
                continue
            try:
                handler()
            except KeyboardInterrupt:
                print("\nAction cancelled. Returning to menu...")
    except (KeyboardInterrupt, EOFError):
        print()
```

### Pattern 3: Capture Device Detection via Index Probing

**What:** Probe `cv2.VideoCapture(i)` for indices 0 through 9 to find available capture devices.

**Why this approach:** OpenCV has no `list_devices()` API. The official OpenCV issue (#23844) requesting this is still open. Probing is the standard workaround used across the community.

**Implementation:**
```python
def detect_capture_devices(max_index: int = 10) -> list[dict]:
    """Probe capture device indices and return available devices."""
    devices = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            devices.append({
                "index": i,
                "width": w,
                "height": h,
                "fps": fps,
            })
            cap.release()
    return devices
```

**Caveats:**
- Probing can be slow (1-2s total) as each failed index may block briefly
- On some platforms, probing may trigger camera access permissions dialogs
- Some virtual devices (OBS Virtual Camera, etc.) may appear as valid indices
- The backend auto-detection in `CaptureSource` should be used for the actual capture, but basic `cv2.VideoCapture(i)` suffices for probing

**Where to place:** `src/hdmi_exfil/receiver/capture/source.py` -- alongside the existing `CaptureSource` class. This keeps all capture device logic in one module.

### Pattern 4: Last Transfer Stats (In-Memory)

**What:** Store the result of the last completed transfer in a module-level variable, display on request.

**Why:** RECV-02 requires a "Last transfer stats" menu item. The architecture research (FEATURES.md D-4) specifies in-memory only -- no persistence. Lost when console exits.

**Implementation:**
```python
# Module-level state
_last_transfer: dict | None = None

def _action_stats() -> None:
    if _last_transfer is None:
        print("No transfer completed yet.")
        return
    print(f"  File: {_last_transfer['filename']}")
    print(f"  Size: {_last_transfer['size']} bytes")
    print(f"  Duration: {_last_transfer['duration']:.2f}s")
    print(f"  Speed: {_last_transfer['speed']:.2f} Mbps")
    print(f"  Integrity: {_last_transfer['integrity']}")
```

**Note:** This requires `run_receive()` to return (or populate) transfer stats. Currently the receive functions print stats but don't return them. Two options:
1. Have `run_receive()` return a stats dict (cleaner but changes the function contract)
2. Capture stdout during receive (hacky, fragile)
3. Store stats in a module-level variable set by the receive functions (pragmatic)

**Recommendation:** Option 3 is simplest for Phase 9. The `_print_receive_stats()` function already computes the values -- add a module-level variable that gets set alongside the print. This avoids changing `run_receive()`'s return type.

### Pattern 5: Settings Action (Informational)

**What:** Display current configuration values. Not persistent (deferred to v1.2 per UX-D1).

**Implementation:**
```python
def _action_settings() -> None:
    print("\nCurrent Settings:")
    print(f"  Default profile: speed")
    print(f"  Default output:  received_files")
    print(f"  Threaded capture: enabled")
    print(f"  Buffer size: 16 frames")
    print()
```

For Phase 9, this is purely informational. Settings persistence is deferred to v1.2 (UX-D1). The menu item exists so the console menu matches the success criteria, but it simply prints defaults.

### Anti-Patterns to Avoid
- **Duplicating receive/decode logic in the console:** Console must ONLY collect parameters and delegate to `run_receive()`. No CaptureSource construction, no protocol decoding, no frame processing in the console module.
- **Constructing argparse.Namespace objects:** Phase 8 initially considered this but rejected it. Extract `run_receive()` with explicit parameters instead of building fake Namespace objects.
- **Adding cv2-enumerate-cameras dependency:** Resist the temptation. Index probing works for 1-2 capture cards, which is the typical HDMI capture use case.
- **Building a Settings editor:** Per REQUIREMENTS.md, UX-D1 (settings persistence) is deferred to v1.2. The Settings action should be informational only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Arrow-key menus | Custom curses/readline menus | InquirerPy `inquirer.select()` | Cross-platform, handles terminal modes, arrow keys, separators, themes. Already proven in Phase 8. |
| File path input with completion | Custom tab-completion | InquirerPy `inquirer.filepath()` or `inquirer.text()` | prompt_toolkit handles OS-specific path completion. |
| Capture device enumeration | Full DirectShow/V4L2 API wrappers | Simple `cv2.VideoCapture(i).isOpened()` probe loop | OpenCV handles backend selection. Probing 10 indices takes 1-2s max. |
| Terminal Ctrl-C handling | Signal handlers, custom exception classes | Python's built-in KeyboardInterrupt + try/except | InquirerPy already raises KeyboardInterrupt on Ctrl-C. Nested try/except (inner for actions, outer for prompts) is the proven pattern from Phase 8. |

**Key insight:** The receiver console is a parameter collector, not a receiver implementation. Every line of actual capture/decode logic already exists in `receive.py` and `calibrate.py`. The console's job is to present a menu, ask questions, and call the existing functions.

## Common Pitfalls

### Pitfall 1: _run_receiver Depends on argparse.Namespace
**What goes wrong:** The internal `_run_receiver()` function reads `args.mode` and `args.output` from an `argparse.Namespace` object. The console cannot easily call it without constructing a fake Namespace.
**Why it happens:** `main()` was written as a monolithic function before the console was envisioned.
**How to avoid:** Extract `run_receive()` with explicit parameters. Refactor `_run_receiver()` to also take explicit `mode` and `output` parameters instead of a Namespace.
**Warning signs:** If you see `argparse.Namespace` being constructed in the console module, the extraction wasn't done properly.

### Pitfall 2: Capture Device Probe Blocking the Console
**What goes wrong:** Probing 10 capture device indices on startup can take 2-5 seconds. If done synchronously before showing the menu, the console feels unresponsive.
**Why it happens:** `cv2.VideoCapture(i)` on non-existent devices may block for 500ms+ per index.
**How to avoid:** Only probe devices when user selects "Detect capture card" or "Receive file". Do NOT probe on console startup. Display "Detecting devices..." message before probing.
**Warning signs:** Console takes several seconds to show the first menu.

### Pitfall 3: InquirerPy + cv2.imshow Window Conflict
**What goes wrong:** During receive, the receiver opens a cv2.imshow debug window. InquirerPy menus use prompt_toolkit terminal input. If both try to handle input simultaneously, behavior is undefined.
**Why it happens:** cv2.imshow creates an OS window with its own event loop. prompt_toolkit uses terminal stdin.
**How to avoid:** They never run simultaneously. The menu collects all parameters BEFORE starting receive. During receive, only cv2 is active. After receive completes, cv2 windows are destroyed and the menu takes over again. This is the same sequential pattern as Phase 8 (InquirerPy then pygame, never concurrent).
**Warning signs:** If you see `inquirer.*` calls inside the receive loop, the architecture is wrong.

### Pitfall 4: Forgetting to Add InquirerPy to Receiver Extras
**What goes wrong:** The console imports InquirerPy but it's only in the `sender` extras. Users who install `pip install hdmi-exfil[receiver]` get an ImportError.
**Why it happens:** Phase 8 added InquirerPy to `sender` extras only. Phase 9 needs it in `receiver` extras too.
**How to avoid:** Add `"InquirerPy >= 0.3.4"` to the `receiver` extras list in `pyproject.toml`.
**Warning signs:** `pip install hdmi-exfil[receiver]` then `hdmi-receiver` fails with ImportError.

### Pitfall 5: Receiver Calibrate Signal vs Sender Calibrate Pattern
**What goes wrong:** The calibrate command has three subcommands: `send`, `recv`, `loopback`. The sender console calls `_cmd_send()` to display a pattern. The receiver console should call `_cmd_recv()` to capture and analyze. But `_cmd_recv()` takes an `args.source` and `args.frames` from argparse.
**Why it happens:** `_cmd_recv()` was written for argparse, same as the receive pipeline.
**How to avoid:** Either extract `_cmd_recv()` parameters to explicit arguments, or construct a minimal `argparse.Namespace(source=..., frames=10)` since calibrate is simpler and the Namespace pattern is reasonable for this small case.
**Warning signs:** If you try to call `_cmd_recv()` directly without an args Namespace and get AttributeError.

## Code Examples

### Example 1: Receiver Console Main Menu
```python
from InquirerPy import inquirer
from InquirerPy.separator import Separator

_MENU_RECEIVE = "Receive file"
_MENU_CALIBRATE = "Calibrate signal"
_MENU_DETECT = "Detect capture card"
_MENU_STATS = "Last transfer stats"
_MENU_SETTINGS = "Settings"
_MENU_QUIT = "Quit"

def _show_main_menu() -> str:
    return inquirer.select(
        message="HDMI Receiver Console",
        choices=[
            _MENU_RECEIVE,
            Separator(),
            _MENU_CALIBRATE,
            _MENU_DETECT,
            Separator(),
            _MENU_STATS,
            _MENU_SETTINGS,
            Separator(),
            _MENU_QUIT,
        ],
    ).execute()
```

### Example 2: Capture Device Detection Action
```python
import cv2

def _detect_devices(max_index: int = 10) -> list[dict]:
    """Probe capture device indices and return available devices."""
    devices = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            devices.append({"index": i, "width": w, "height": h, "fps": fps})
            cap.release()
    return devices

def _action_detect() -> None:
    print("\nDetecting capture devices...")
    devices = _detect_devices()
    if not devices:
        print("No capture devices found.")
    else:
        print(f"Found {len(devices)} device(s):")
        for d in devices:
            print(f"  Device {d['index']}: {d['width']}x{d['height']} @ {d['fps']:.0f} FPS")
    print()
```

### Example 3: Receive File Action with Parameter Collection
```python
def _action_receive() -> None:
    """Collect receive parameters via prompts and delegate to run_receive()."""
    # 1. Detect and select capture device (RECV-03)
    print("Detecting capture devices...")
    devices = _detect_devices()
    if not devices:
        print("No capture devices found. Connect a capture card and try again.")
        return

    if len(devices) == 1:
        source = devices[0]["index"]
        d = devices[0]
        print(f"  Using device {source}: {d['width']}x{d['height']} @ {d['fps']:.0f} FPS")
    else:
        device_choices = [
            {
                "name": f"Device {d['index']}: {d['width']}x{d['height']} @ {d['fps']:.0f} FPS",
                "value": d["index"],
            }
            for d in devices
        ]
        source = inquirer.select(
            message="Capture device:",
            choices=device_choices,
        ).execute()

    # 2. Resolution profile (RECV-04)
    profile_choices = [
        {"name": "speed (1080p @ 240fps)", "value": "speed"},
        {"name": "balanced (1080p @ 60fps)", "value": "balanced"},
        {"name": "quality (4K @ 30fps)", "value": "quality"},
    ]
    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=profile_choices,
    ).execute()
    profile = PROFILES[profile_name]

    # 3. Output directory (RECV-05)
    output = inquirer.text(
        message="Output directory:",
        default="received_files",
    ).execute()

    # 4. Receive mode
    mode = inquirer.select(
        message="Receive mode:",
        choices=["auto", "sequential", "fountain"],
        default="auto",
    ).execute()

    # Delegate to extracted run_receive()
    run_receive(
        source=source,
        mode=mode,
        profile=profile,
        output=output,
    )
```

### Example 4: run_receive() Extraction
```python
def run_receive(
    source: int | str,
    mode: str = "auto",
    profile: ResolutionProfile | None = None,
    output: str = "received_files",
    threaded: bool = True,
    buffer_size: int = 16,
) -> None:
    """Execute the full receive pipeline with explicit parameters."""
    profile = profile or DEFAULT_PROFILE

    # Parse source: numeric string -> camera index
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    print(f"Opening video source: {source}")

    try:
        cap = CaptureSource(
            source, width=profile.width, height=profile.height,
            fps=profile.target_fps,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return  # Don't sys.exit -- return to menu

    print(f"Camera: {cap.actual_width}x{cap.actual_height} @ {cap.actual_fps} FPS")

    with cap:
        if threaded:
            tcap = ThreadedCapture(cap, buffer_size=buffer_size)
            with tcap:
                print(f"Threaded capture: buffer_size={buffer_size} frames")
                _dispatch_receive(tcap, mode, output, profile)
        else:
            _dispatch_receive(cap, mode, output, profile)
```

**CRITICAL difference from sender:** `run_receive()` must NOT call `sys.exit(1)` on errors. When called from the console, it should `return` so the user gets back to the menu. When called from `main()` (CLI), `main()` can catch and `sys.exit()` if needed.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `main()` with argparse + all logic | Extract `run_*()` + thin `main()` | Phase 8 (sender) | Enables interactive console delegation |
| No device enumeration in OpenCV | Still no official API; community uses probing or cv2-enumerate-cameras | Ongoing (OpenCV issue #23844) | Index probing is the pragmatic solution |
| InquirerPy in sender extras only | Must add to receiver extras too | Phase 9 | Needed for `hdmi-receiver` entry point |

**Deprecated/outdated:**
- Building fake `argparse.Namespace` objects to call existing functions -- Phase 8 proved extraction is cleaner.
- `cv2-enumerate-cameras` package exists but introduces an unnecessary dependency for this use case.

## Open Questions

1. **Last transfer stats data source**
   - What we know: The receive functions print stats via `_print_receive_stats()` but don't return or store them.
   - What's unclear: Best mechanism to capture stats for the "Last transfer stats" menu item.
   - Recommendation: Add a module-level `_last_transfer` variable in `receive.py` that gets set alongside `_print_receive_stats()`. Console reads this variable to display stats. Simple, no API changes needed.

2. **Settings menu depth**
   - What we know: RECV-02 lists "Settings" as a menu item. UX-D1 (settings persistence) is deferred to v1.2.
   - What's unclear: Should Settings display just current defaults, or allow temporary overrides for the session?
   - Recommendation: Display-only for Phase 9. Print the current defaults (profile, output dir, threaded, buffer size). No editing, no persistence. This satisfies the menu requirement without scope creep.

3. **Calibrate signal flow**
   - What we know: `calibrate.py` has `_cmd_recv()` that takes an argparse Namespace with `source` and `frames` attributes.
   - What's unclear: Whether to extract explicit parameters or construct a minimal Namespace.
   - Recommendation: Construct a minimal `argparse.Namespace(source=str(device_index), frames=10)` for the calibrate call. Calibrate is a small utility and the Namespace is simple (2 fields). Full extraction would be over-engineering for this use case.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/hdmi_exfil/sender/cli/console.py` -- verified working sender console pattern (Phase 8)
- Existing codebase: `src/hdmi_exfil/receiver/cli/receive.py` -- current monolithic main() to refactor
- Existing codebase: `tests/test_sender_console.py` -- test pattern to mirror
- InquirerPy Context7 docs (`/kazhala/inquirerpy`) -- select prompt, filepath prompt, keybindings verified
- pyproject.toml -- current dependency structure, entry points, extras

### Secondary (MEDIUM confidence)
- [cv2-enumerate-cameras on PyPI](https://pypi.org/project/cv2-enumerate-cameras/) -- v1.3.3, cross-platform device enumeration (verified via PyPI page)
- [OpenCV issue #23844](https://github.com/opencv/opencv/issues/23844) -- confirms no built-in device enumeration API
- [Community camera probing pattern](https://gist.github.com/keizerzilla/2d6369df47d23e44af4422efa419113c) -- index probing approach

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- InquirerPy already proven in Phase 8, same version, same patterns
- Architecture: HIGH -- exact mirror of sender console pattern with minor receiver-specific additions
- Pitfalls: HIGH -- most pitfalls are direct parallels to sender console pitfalls, already resolved in Phase 8
- Device detection: MEDIUM -- index probing is widely used but untested in this specific codebase

**Research date:** 2026-03-03
**Valid until:** 2026-04-03 (stable -- all technologies are mature)
