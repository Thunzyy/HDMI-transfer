# Feature Landscape

**Domain:** Interactive CLI consoles and monorepo restructure for HDMI data exfiltration tool
**Researched:** 2026-03-02
**Overall confidence:** MEDIUM (InquirerPy well-known from training data, but no live verification of latest version; monorepo patterns from setuptools/pip extras are stable and well-documented)

## Table Stakes

Features users expect. Missing = the interactive console feels broken or incomplete.

### Console Menu Features

| Feature | Why Expected | Complexity | Dependencies | Notes |
|---------|--------------|------------|--------------|-------|
| **TS-1: Arrow-key navigation main menu** | This is the defining feature of an interactive console. Users expect Up/Down arrows to highlight options and Enter to select. Without this, there is no "interactive console" -- it is just argparse. | Low | InquirerPy `inquirer.select()` | InquirerPy wraps prompt-toolkit and provides list/select prompts with arrow-key navigation out of the box. Both sender and receiver get a main menu with their respective actions. |
| **TS-2: Sender main menu actions** | Sender users expect to pick from the core operations: send file (Python), send file (web/browser), calibrate, detect hardware, benchmark, settings. These map 1:1 to existing CLI commands. | Low | Existing `cli/send.py`, `cli/calibrate.py`, `cli/benchmark.py`, `display/monitors.py` | Each menu action calls into existing functions. The console is a thin wrapper that collects parameters interactively instead of via argparse flags. |
| **TS-3: Receiver main menu actions** | Receiver users expect: receive file, calibrate signal, detect capture card, view last transfer stats, settings. Maps to existing `cli/receive.py` and `cli/calibrate.py`. | Low | Existing `cli/receive.py`, `cli/calibrate.py` | Same pattern as sender -- interactive wrapper over existing functionality. |
| **TS-4: Interactive file picker for send** | When user selects "Send File (Python)", they need to specify a file path. A text input prompt with path completion or at minimum a clear text input is expected. Bare `input()` with no guidance is poor UX. | Low | InquirerPy `inquirer.filepath()` or `inquirer.text()` | InquirerPy has a `filepath` prompt type with path auto-completion. This replaces the positional `input_path` argparse argument. |
| **TS-5: Profile selection prompt** | Before sending or receiving, user must pick a resolution profile (speed/balanced/quality). Arrow-key selection from the three options is natural. | Low | InquirerPy `inquirer.select()`, `config.PROFILES` | Display profile name + description (e.g., "speed -- 1080p@240fps"). Pre-select the last-used or default profile. |
| **TS-6: Mode selection prompt** | User must choose encoding mode (sequential/fountain) for send, or auto/sequential/fountain for receive. | Low | InquirerPy `inquirer.select()` | Simple 2-3 option list. Default to fountain for send (higher throughput), auto for receive. |
| **TS-7: Monitor/capture device selection** | Sender needs to pick which monitor to display on. Receiver needs to pick which capture device. Both should list detected hardware and let user arrow-select. | Medium | `display/monitors.get_monitors()`, OpenCV `cv2.VideoCapture` enumeration | Monitor detection already works via screeninfo. Capture device enumeration is trickier -- OpenCV does not have a clean "list devices" API. On Windows, can probe indices 0-9. Display device name if available. |
| **TS-8: Graceful exit and Ctrl-C handling** | User expects Ctrl-C to cleanly exit at any point, returning to the main menu or exiting the program without a stack trace. | Low | Python `KeyboardInterrupt` handling, InquirerPy built-in Ctrl-C support | InquirerPy raises `KeyboardInterrupt` on Ctrl-C during prompts. Wrap console loop in try/except. Transfers should also handle Ctrl-C (existing ESC-to-pause logic can be extended). |
| **TS-9: Return to main menu after action** | After a send/receive/calibrate completes, user expects to return to the main menu rather than the program exiting. This is what makes it a "console" rather than a single-shot command. | Low | Console main loop | Simple while-True loop wrapping the menu prompt. Actions run and control returns to menu. "Exit" option at bottom of menu. |
| **TS-10: Clear screen / visual separation between actions** | After completing an action and returning to the menu, the terminal should be visually distinct -- either clear the screen or print a separator. Otherwise prior output clutters the menu. | Low | `os.system('cls' or 'clear')` or print separators | Simple terminal clear before re-showing the menu. Keep it minimal -- no need for a full TUI framework. |

### Monorepo Restructure Features

| Feature | Why Expected | Complexity | Dependencies | Notes |
|---------|--------------|------------|--------------|-------|
| **TS-11: pip install with extras** | `pip install hdmi-exfil[sender]` installs only sender deps (pygame-ce, screeninfo). `pip install hdmi-exfil[receiver]` installs only receiver deps (opencv-python). `pip install hdmi-exfil[all]` installs everything. This is the stated goal. | Medium | pyproject.toml `[project.optional-dependencies]` | Core deps (numpy, numba) stay in base. pygame-ce, screeninfo go to `[sender]`. opencv-python goes to `[receiver]`. InquirerPy goes to both (or base if shared). |
| **TS-12: Clean module separation** | `src/core/` for shared protocol/encoding code, `src/sender/` for sender-specific code, `src/receiver/` for receiver-specific code. Currently everything is flat under `src/`. | High | All existing modules need to be relocated | This is the most complex task. Imports change across the entire codebase. Tests need updating. Need to avoid breaking existing functionality. The `protocols/`, `file_handling/`, `config.py`, `prng.py` go to core. `display/` goes to sender. `capture/` goes to receiver. `cli/` splits. |
| **TS-13: Console entry points** | New entry points `hdmi-sender` and `hdmi-receiver` for the interactive consoles, alongside existing `hdmi-send`, `hdmi-recv`, etc. for direct argparse use. | Low | pyproject.toml `[project.scripts]` | Two new script entries. Existing entry points stay for backward compatibility and scripting/automation use. |
| **TS-14: Existing CLI commands still work** | `hdmi-send`, `hdmi-recv`, `hdmi-calibrate`, `hdmi-bench` must continue to work unchanged after restructure. The interactive consoles are additive, not replacements. | Medium | All existing `cli/*.py` modules | This is a hard constraint. The argparse CLIs are the scripting interface. The interactive consoles are the human interface. Both must coexist. |

## Differentiators

Features that elevate the console experience beyond a basic menu. Not expected, but valued.

| Feature | Value Proposition | Complexity | Dependencies | Notes |
|---------|-------------------|------------|--------------|-------|
| **D-1: Settings persistence** | Remember last-used profile, mode, screen index, output directory across sessions. Saves user from re-selecting defaults every time they launch the console. | Medium | JSON config file (~/.hdmi-exfil/config.json or similar) | InquirerPy supports `default` parameter on prompts. Load saved settings and pass as defaults. Save after each successful action. |
| **D-2: Live hardware status on menu** | Show detected monitors and capture devices in the menu header before user selects an action. e.g., "2 monitors detected, Elgato 4K X on index 1". User knows hardware state without running a separate detect command. | Medium | `get_monitors()`, device probe on startup | Run detection once on console startup. Display as header text above menu. Refresh only when user selects "Detect Hardware". Avoid slow startup -- if detection takes >1s, show "detecting..." and update async. |
| **D-3: Confirm before send/receive** | After collecting all parameters (file, profile, mode, screen), show a summary and ask for confirmation before starting the transfer. Prevents accidental sends with wrong settings. | Low | InquirerPy `inquirer.confirm()` | Simple yes/no confirmation prompt showing all selected parameters. |
| **D-4: Last transfer stats on receiver menu** | Receiver menu shows summary of last completed transfer (filename, size, speed, integrity status) without needing to scroll through terminal history. | Low | In-memory state from last transfer | Store last transfer result in a module-level variable. Display in menu header or as a dedicated menu action. |
| **D-5: Fuzzy file path input** | InquirerPy's fuzzy finder for file selection -- type partial filename and it filters. Better than raw text input for finding files. | Low | InquirerPy `inquirer.fuzzy()` or `filepath` with completion | InquirerPy supports fuzzy matching. Use for file path input if the prompt type supports it. Falls back to text input gracefully. |
| **D-6: Colored output and status indicators** | Use terminal colors to indicate status: green for success, red for errors, yellow for warnings, cyan for info. Makes the console feel polished. | Low | ANSI escape codes or `colorama` or built-in InquirerPy styling | InquirerPy uses prompt-toolkit which supports rich terminal styling. Can color menu items, headers, and status messages. Avoid adding heavy dependencies -- ANSI codes work on Windows 10+ terminals. |
| **D-7: Sender web-launch integration** | "Send File (Web)" menu option opens sender.html in the default browser with one keypress. Currently user has to manually open the HTML file. | Low | `webbrowser.open()` stdlib | Python stdlib `webbrowser` module opens default browser. Just need to locate sender.html relative to package installation. |
| **D-8: Advanced settings submenu** | Expose less-common settings (FPS override, redundancy, buffer size, threaded capture toggle) in a nested submenu rather than cluttering the main menu. | Low | InquirerPy `inquirer.number()`, `inquirer.select()` | Keep main menu clean (6-7 items). "Settings" opens a submenu for advanced tweaks. Defaults are sensible -- most users never touch these. |

## Anti-Features

Features to explicitly NOT build. Common mistakes when adding interactivity to CLI tools.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **AF-1: Full TUI framework (curses, textual, rich TUI)** | The consoles need arrow-key menus, not a full terminal UI with panels, layouts, and widgets. Textual/curses add massive complexity, require careful terminal handling, and conflict with existing cv2.imshow windows and pygame displays. InquirerPy is intentionally lightweight -- it takes over the terminal only during prompts, then releases it for normal stdout. | Use InquirerPy for prompts only. Regular print() for output. No persistent TUI layout. The console is a prompt loop, not a dashboard. |
| **AF-2: Async/concurrent menu updates** | Do not try to update the menu in real-time while a transfer is running. Transfers use cv2.imshow, pygame, and stdout writes that are incompatible with a concurrent TUI. | Menu is shown only when no transfer is active. During transfers, existing progress reporting (stdout writes) continues unchanged. Return to menu after transfer completes. |
| **AF-3: Custom keybindings beyond arrow keys** | Do not invent custom keyboard shortcuts (Ctrl-S to send, F5 to refresh, etc.). This creates a learning curve and conflicts with terminal shortcuts. | Arrow keys + Enter + Ctrl-C is the complete interaction model. All actions are accessible through the menu. No hidden shortcuts. |
| **AF-4: Configuration file format bikeshedding** | Do not implement TOML, YAML, or INI config files when JSON suffices. The settings are simple key-value pairs. | If settings persistence is implemented, use JSON. One file. No schema validation beyond basic type checks. |
| **AF-5: Plugin system or extensible menus** | Do not add plugin architecture to extend the console with custom menu items. This is a single-purpose tool with a fixed set of operations. | Hardcode the menu items. If new features are added, add them to the menu directly. |
| **AF-6: Replacing argparse CLIs with console-only interface** | Do not remove or deprecate the existing argparse-based commands. They are essential for scripting, automation, CI/CD, and headless operation. The interactive consoles are an addition, not a replacement. | Both interfaces coexist. `hdmi-send` (argparse) and `hdmi-sender` (interactive) share the same underlying functions but differ in parameter collection. |
| **AF-7: Auto-update or version checking** | Do not add update checking, version comparison, or auto-update features to the console. This is a local tool that should work offline. | Version is in pyproject.toml. Users update manually with pip. |
| **AF-8: Transfer history database** | Do not build a SQLite or file-based transfer history. Last transfer stats in-memory is sufficient. Historical data adds complexity with minimal value for this tool's use case. | Store last transfer result in memory. Display on request. Lost when console exits. That is fine. |

## Feature Dependencies

```
TS-12 (Module separation)
  |
  +---> TS-11 (pip extras) -- extras reference separated modules
  |       |
  |       +---> TS-13 (Console entry points) -- entry points need correct module paths
  |
  +---> TS-14 (Existing CLIs work) -- must not break during restructure

TS-1 (Arrow-key menu) -- InquirerPy
  |
  +---> TS-2 (Sender menu actions) -- menus call into existing sender functions
  |       |
  |       +---> TS-4 (File picker) -- send action needs file selection
  |       |
  |       +---> TS-5 (Profile selection) -- send action needs profile
  |       |
  |       +---> TS-6 (Mode selection) -- send action needs mode
  |       |
  |       +---> TS-7 (Monitor selection) -- send action needs target screen
  |
  +---> TS-3 (Receiver menu actions) -- menus call into existing receiver functions
  |       |
  |       +---> TS-7 (Device selection) -- receive action needs capture source
  |
  +---> TS-8 (Ctrl-C handling) -- all prompts need clean exit
  |
  +---> TS-9 (Return to menu) -- console loop wraps menu
  |
  +---> TS-10 (Clear screen) -- visual reset between actions

D-1 (Settings persistence)
  |
  +---> D-8 (Advanced settings submenu) -- settings need saving

D-2 (Live hardware status) -- independent, runs at startup

D-3 (Confirm before send) -- independent, added to send/receive flow

D-4 (Last transfer stats) -- independent, in-memory

D-7 (Web launch) -- independent, stdlib only
```

### Critical Path

The monorepo restructure (TS-12) is the highest-risk, highest-effort feature and blocks pip extras (TS-11). The interactive console (TS-1 through TS-10) is mostly independent of the restructure -- it could be built before or after. However, if built after the restructure, the import paths will be correct from the start, avoiding double-migration.

**Recommended order:**
1. Module separation (TS-12) first -- highest risk, do it while codebase is stable
2. Pip extras and entry points (TS-11, TS-13) -- wire up the new structure
3. Verify existing CLIs (TS-14) -- ensure nothing broke
4. Sender console (TS-1, TS-2, TS-4-7, TS-8-10) -- interactive sender
5. Receiver console (TS-3, TS-7, TS-8-10) -- interactive receiver
6. Differentiators (D-1 through D-8) -- polish

## MVP Recommendation

**Prioritize these table stakes first:**

1. **TS-12: Module separation** -- Highest risk, must be done carefully with all tests passing after each move. This is the structural foundation.
2. **TS-11: pip extras** -- Wire up the separated modules in pyproject.toml. Verify `pip install -e .[sender]`, `.[receiver]`, `.[all]` all work.
3. **TS-14: Existing CLIs work** -- Run full test suite. Run each CLI command manually. Non-negotiable.
4. **TS-1 + TS-2 + TS-9: Sender console (basic)** -- Main menu with arrow keys, 6 actions, return-to-menu loop.
5. **TS-1 + TS-3 + TS-9: Receiver console (basic)** -- Main menu with arrow keys, 5 actions, return-to-menu loop.
6. **TS-4 + TS-5 + TS-6 + TS-7: Interactive parameter collection** -- File picker, profile select, mode select, device select.
7. **TS-8 + TS-10: Polish** -- Ctrl-C handling, screen clearing.

**Defer these to post-MVP:**
- **D-1 (Settings persistence):** Nice to have but not needed for functional console. Users can re-select each time initially.
- **D-2 (Live hardware status):** Adds startup latency. Users can use "Detect Hardware" menu action.
- **D-5 (Fuzzy file path):** Standard text input with filepath completion is sufficient for MVP.
- **D-8 (Advanced settings submenu):** Use sensible defaults. Add submenu later if users request fine-tuning.

## Complexity Assessment

| Feature Group | Estimated Effort | Risk Level | Notes |
|---------------|-----------------|------------|-------|
| Module separation (TS-12) | 4-6 hours | HIGH | Every import path changes. Tests must all pass. One mistake breaks everything. |
| pip extras (TS-11, TS-13) | 1-2 hours | LOW | pyproject.toml changes only. Well-documented pattern. |
| Backward compat (TS-14) | 1-2 hours | MEDIUM | Testing and fixing import issues from restructure. |
| Sender console (TS-1,2,4-7,8-10) | 3-4 hours | LOW | InquirerPy is straightforward. Mostly wiring prompts to existing functions. |
| Receiver console (TS-1,3,7,8-10) | 2-3 hours | LOW | Same pattern as sender, fewer options. |
| Differentiators (D-1 through D-8) | 3-4 hours total | LOW | All are small, independent additions. |
| **Total** | **14-21 hours** | | |

## Sources

### InquirerPy (MEDIUM confidence -- training data, no live verification)
- InquirerPy is a Python port of Inquirer.js, built on prompt-toolkit
- Supports prompt types: select (list), checkbox, confirm, text, filepath, fuzzy, number, password, expand, rawlist
- Latest known version: 0.3.4 (as of training data cutoff)
- License: MIT
- Dependencies: prompt-toolkit >= 3.0.1, pfzy >= 0.3.1
- Works on Windows, Linux, macOS
- Arrow-key navigation is the default for select/list prompts

### setuptools pip extras (HIGH confidence -- stable, well-documented pattern)
- `[project.optional-dependencies]` in pyproject.toml is the standard PEP 621 mechanism
- `pip install package[extra]` syntax has been stable for years
- Multiple extras can be defined: `[sender]`, `[receiver]`, `[all]`, `[dev]`
- The `[all]` extra typically includes all other extras via cross-referencing

### Python CLI console patterns (MEDIUM confidence -- training data)
- Interactive prompt libraries (InquirerPy, questionary, PyInquirer) all follow the Inquirer.js pattern
- The standard pattern is: prompt loop -> collect parameters -> execute action -> return to prompt
- Clean separation between parameter collection (interactive prompts) and execution (existing functions) is the best practice
- Ctrl-C handling via KeyboardInterrupt is universal across all prompt libraries
