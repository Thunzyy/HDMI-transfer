"""Interactive sender console -- arrow-key menu-driven sender interface.

Launches with ``hdmi-sender`` and provides an interactive menu for all
sender operations: send file, calibrate, detect hardware, benchmark.

Usage::

    hdmi-sender
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from InquirerPy import inquirer
from InquirerPy.separator import Separator

from hdmi_exfil.core.config import PROFILES, ResolutionProfile
from hdmi_exfil.core import settings
from hdmi_exfil.sender.cli.send import run_send
from hdmi_exfil.sender.display.monitors import get_monitors


# ------------------------------------------------------------------
# Menu constants
# ------------------------------------------------------------------

_MENU_SEND_PYTHON = "Send file (Python)"
_MENU_SEND_BROWSER = "Send file (Browser)"
_MENU_CALIBRATE = "Calibrate"
_MENU_DETECT = "Detect hardware"
_MENU_BENCHMARK = "Benchmark"
_MENU_SETTINGS = "Settings"
_MENU_QUIT = "Quit"


def _show_main_menu() -> str:
    """Display the main menu and return the selected action string."""
    return inquirer.select(
        message="HDMI Sender Console",
        choices=[
            _MENU_SEND_PYTHON,
            _MENU_SEND_BROWSER,
            Separator(),
            _MENU_CALIBRATE,
            _MENU_DETECT,
            _MENU_BENCHMARK,
            Separator(),
            _MENU_SETTINGS,
            _MENU_QUIT,
        ],
    ).execute()


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------


def _action_send_python() -> None:
    """Collect send parameters via prompts and delegate to run_send()."""
    cfg = settings.load()["sender"]

    # 1. File path with tab-completion (SEND-03)
    file_path = inquirer.filepath(
        message="File to send:",
        validate=lambda p: os.path.isfile(p),
        invalid_message="File does not exist",
    ).execute()

    # 2. Resolution profile (SEND-04)
    default_profile = cfg.get("profile", "speed")
    profile_choices = [
        {"name": "speed (1080p @ 240fps)", "value": "speed"},
        {"name": "balanced (1080p @ 60fps)", "value": "balanced"},
        {"name": "quality (4K @ 30fps)", "value": "quality"},
    ]
    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=profile_choices,
        default=default_profile,
    ).execute()
    profile = PROFILES[profile_name]

    # 3. Encoding mode (SEND-05)
    default_mode = cfg.get("mode", "sequential")
    mode = inquirer.select(
        message="Encoding mode:",
        choices=["sequential", "fountain"],
        default=default_mode,
    ).execute()

    # 4. Target monitor (SEND-06)
    monitors = get_monitors()
    saved_monitor = cfg.get("monitor")
    if saved_monitor is not None and saved_monitor < len(monitors):
        m = monitors[saved_monitor]
        print(f"  Using saved monitor {saved_monitor}: "
              f"{m['width']}x{m['height']} at ({m['left']},{m['top']})")
        screen = saved_monitor
    elif len(monitors) == 1:
        screen = 0
        print(f"  Using monitor 0: {monitors[0]['width']}x{monitors[0]['height']}")
    else:
        monitor_choices = [
            {
                "name": f"Monitor {i}: {m['width']}x{m['height']}"
                f" at ({m['left']},{m['top']})",
                "value": i,
            }
            for i, m in enumerate(monitors)
        ]
        screen = inquirer.select(
            message="Target monitor:",
            choices=monitor_choices,
        ).execute()

    # Delegate to extracted run_send()
    run_send(
        input_path=file_path,
        mode=mode,
        profile=profile,
        screen=screen,
    )


def _action_send_browser() -> None:
    """Open the browser-based sender HTML file."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "sender.html"),
        os.path.join(os.getcwd(), "sender.html"),
    ]
    for candidate in candidates:
        resolved = os.path.normpath(candidate)
        if os.path.isfile(resolved):
            print(f"Opening {resolved} in browser...")
            webbrowser.open(f"file://{resolved}")
            return
    print("sender.html not found. Expected in project root directory.")
    print("Run from the project directory or open sender.html manually.")


def _action_calibrate() -> None:
    """Display calibration pattern via existing calibrate send command."""
    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=list(PROFILES.keys()),
        default="speed",
    ).execute()
    profile = PROFILES[profile_name]

    # Import and call the calibrate send function
    from hdmi_exfil.receiver.cli.calibrate import _cmd_send

    # Build a minimal args namespace with renderer attribute
    args = argparse.Namespace(renderer="pygame")
    _cmd_send(profile, args)


def _action_detect() -> None:
    """Detect and display connected monitors."""
    monitors = get_monitors()
    print(f"\nDetected {len(monitors)} monitor(s):")
    for i, m in enumerate(monitors):
        print(
            f"  Monitor {i}: {m['width']}x{m['height']}"
            f" at ({m['left']}, {m['top']})"
        )
    print()


def _action_benchmark() -> None:
    """Run benchmark with interactively selected parameters."""
    from hdmi_exfil.core.cli.benchmark import run_benchmark

    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=list(PROFILES.keys()),
        default="speed",
    ).execute()

    mode = inquirer.select(
        message="Encoding mode:",
        choices=["sequential", "fountain"],
        default="fountain",
    ).execute()

    profile = PROFILES[profile_name]
    print(f"\nBenchmarking {mode} mode with {profile_name} profile...")
    result = run_benchmark(profile=profile, mode=mode)

    # Print human-readable results
    print(f"\nResults:")
    print(f"  Frames/sec:  {result.frames_per_sec:.2f}")
    print(f"  Bytes/sec:   {result.bytes_per_sec:.2f}")
    print(f"  Overhead:    {result.overhead_pct:.2f}%")
    print(f"  Error rate:  {result.error_rate:.6f}")
    print(f"  Duration:    {result.duration_sec:.3f}s")
    print()


# ------------------------------------------------------------------
# Dispatch and main loop
# ------------------------------------------------------------------

def _action_settings() -> None:
    """View and edit persistent sender settings."""
    cfg = settings.load()["sender"]
    print(f"\nSender Settings ({settings.settings_path()}):")
    print(f"  Monitor:   {cfg.get('monitor') if cfg.get('monitor') is not None else '(auto-detect)'}")
    print(f"  Profile:   {cfg.get('profile', 'speed')}")
    print(f"  Mode:      {cfg.get('mode', 'sequential')}")
    print()

    action = inquirer.select(
        message="Edit settings?",
        choices=["Change monitor", "Change profile", "Change mode", "Back to menu"],
    ).execute()

    if action == "Change monitor":
        monitors = get_monitors()
        choices = [
            {
                "name": f"Monitor {i}: {m['width']}x{m['height']}"
                f" at ({m['left']},{m['top']})",
                "value": i,
            }
            for i, m in enumerate(monitors)
        ] + [{"name": "(none — always ask)", "value": None}]
        picked = inquirer.select(message="Default monitor:", choices=choices).execute()
        settings.set_value("sender", "monitor", picked)
        print(f"  Saved: monitor = {picked}")

    elif action == "Change profile":
        picked = inquirer.select(
            message="Default profile:",
            choices=list(PROFILES.keys()),
            default=cfg.get("profile", "speed"),
        ).execute()
        settings.set_value("sender", "profile", picked)
        print(f"  Saved: profile = {picked}")

    elif action == "Change mode":
        picked = inquirer.select(
            message="Default mode:",
            choices=["sequential", "fountain"],
            default=cfg.get("mode", "sequential"),
        ).execute()
        settings.set_value("sender", "mode", picked)
        print(f"  Saved: mode = {picked}")
    print()


_DISPATCH = {
    _MENU_SEND_PYTHON: _action_send_python,
    _MENU_SEND_BROWSER: _action_send_browser,
    _MENU_CALIBRATE: _action_calibrate,
    _MENU_DETECT: _action_detect,
    _MENU_BENCHMARK: _action_benchmark,
    _MENU_SETTINGS: _action_settings,
}


def main() -> None:
    """Entry point for ``hdmi-sender`` interactive console."""
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
        print()  # clean newline on exit
