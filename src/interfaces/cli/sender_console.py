"""Interactive sender console -- arrow-key menu-driven sender interface.

Launches with ``hdmi-sender`` and provides an interactive menu for all
sender operations: send file, calibrate, detect hardware, benchmark.

Usage::

    hdmi-sender
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import os
from pathlib import Path
import webbrowser

from InquirerPy import inquirer
from InquirerPy.separator import Separator

from hdmi_transfer.core.config import PROFILES
from hdmi_transfer.core import settings
from hdmi_transfer.interfaces.cli.send import run_send
from hdmi_transfer.sender.display.monitors import get_monitors
from hdmi_transfer.domain.transfer_defaults import (
    DEFAULT_BITS_PER_CHANNEL,
    DEFAULT_MODE,
    DEFAULT_PROFILE_NAME,
)


# ------------------------------------------------------------------
# Menu constants
# ------------------------------------------------------------------

_MENU_SEND_PYTHON = "Send file (Python)"
_MENU_SEND_BROWSER = "Send file (Browser)"
_MENU_CALIBRATE = "Display test patterns"
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


def _saved_bpc(cfg: dict) -> int:
    value = cfg.get("bpc", DEFAULT_BITS_PER_CHANNEL)
    return value if value in (1, 2, 3) else DEFAULT_BITS_PER_CHANNEL


def _action_send_python() -> None:
    """Collect send parameters via prompts and delegate to run_send()."""
    cfg = settings.load()["sender"]

    # 1. File path with tab-completion (SEND-03)
    file_path = inquirer.filepath(
        message="File to send:",
        validate=lambda p: os.path.isfile(p.strip('"').strip("'")),
        invalid_message="File does not exist",
    ).execute().strip('"').strip("'")

    # 2. Resolution profile (SEND-04)
    default_profile = cfg.get("profile", DEFAULT_PROFILE_NAME)
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
    profile = replace(PROFILES[profile_name], bits_per_channel=_saved_bpc(cfg))

    # 3. Encoding mode (SEND-05)
    default_mode = cfg.get("mode", DEFAULT_MODE)
    mode = inquirer.select(
        message="Encoding mode:",
        choices=["sequential", "fountain"],
        default=default_mode,
    ).execute()

    # 4. Target monitor (SEND-06)
    monitors = get_monitors()
    saved_monitor = cfg.get("monitor")
    if isinstance(saved_monitor, int) and 0 <= saved_monitor < len(monitors):
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

    print(f"  Encoding: {profile.bits_per_channel} bits per channel (change in Settings)")
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
            webbrowser.open(Path(resolved).resolve().as_uri())
            return
    from hdmi_transfer.interfaces.browser_sender import render_sender_html

    output = settings.settings_path().parent / "sender.html"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_sender_html(), encoding="utf-8")
    except OSError as exc:
        print(f"Unable to prepare the standalone sender: {exc}")
        return
    print(f"Opening {output} in browser...")
    webbrowser.open(output.resolve().as_uri())


def _action_calibrate() -> None:
    """Display calibration pattern via existing calibrate send command."""
    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=list(PROFILES.keys()),
        default=DEFAULT_PROFILE_NAME,
    ).execute()
    profile = PROFILES[profile_name]

    # Import and call the calibrate send function
    from hdmi_transfer.interfaces.cli.calibrate import _cmd_send

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
    from hdmi_transfer.core.cli.benchmark import run_benchmark

    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=list(PROFILES.keys()),
        default=DEFAULT_PROFILE_NAME,
    ).execute()

    mode = inquirer.select(
        message="Encoding mode:",
        choices=["sequential", "fountain"],
        default=DEFAULT_MODE,
    ).execute()

    profile = replace(
        PROFILES[profile_name], bits_per_channel=_saved_bpc(settings.load()["sender"]),
    )
    print(f"\nBenchmarking {mode} mode with {profile_name} profile...")
    result = run_benchmark(profile=profile, mode=mode)

    # Print human-readable results
    print(f"\nResults:")
    print(f"  Frames/sec:  {result.frames_per_sec:.2f}")
    print(f"  Bytes/sec:   {result.bytes_per_sec:.2f}")
    print(f"  Overhead:    {result.overhead_pct:.2f}%")
    print(f"  Error rate:  {result.error_rate:.6f}")
    print(f"  Duration:    {result.duration_sec:.3f}s")
    print(f"  Completed:   {result.completed}")
    print(f"  Integrity:   {result.integrity_ok}")
    print(f"  Timed out:   {result.timed_out}")
    if not result.completed or not result.integrity_ok:
        print("  Benchmark failed: no verified complete transfer.")
    print("  These are software measurements, not HDMI hardware throughput.")
    print()


# ------------------------------------------------------------------
# Dispatch and main loop
# ------------------------------------------------------------------

def _action_settings() -> None:
    """View and edit persistent sender settings."""
    cfg = settings.load()["sender"]
    print(f"\nSender Settings ({settings.settings_path()}):")
    print(f"  Monitor:   {cfg.get('monitor') if cfg.get('monitor') is not None else '(auto-detect)'}")
    print(f"  Profile:   {cfg.get('profile', DEFAULT_PROFILE_NAME)}")
    print(f"  Mode:      {cfg.get('mode', DEFAULT_MODE)}")
    print(f"  Encoding:  {_saved_bpc(cfg)} bits per channel")
    print()

    action = inquirer.select(
        message="Edit settings?",
        choices=[
            "Change monitor", "Change profile", "Change mode", "Change encoding",
            "Recalibrate next transfer", "Back to menu",
        ],
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
            default=cfg.get("profile", DEFAULT_PROFILE_NAME),
        ).execute()
        settings.set_value("sender", "profile", picked)
        print(f"  Saved: profile = {picked}")

    elif action == "Change mode":
        picked = inquirer.select(
            message="Default mode:",
            choices=["sequential", "fountain"],
            default=cfg.get("mode", DEFAULT_MODE),
        ).execute()
        settings.set_value("sender", "mode", picked)
        print(f"  Saved: mode = {picked}")
    elif action == "Change encoding":
        picked = inquirer.select(
            message="Bits per color channel:", choices=[1, 2, 3], default=_saved_bpc(cfg),
        ).execute()
        settings.set_value("sender", "bpc", picked)
        print(f"  Saved: encoding = {picked} bpc")
    elif action == "Recalibrate next transfer":
        settings.set_value("sender", "calibration_confirmation", None)
        print("  The next send will wait for receiver confirmation before file data.")
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
