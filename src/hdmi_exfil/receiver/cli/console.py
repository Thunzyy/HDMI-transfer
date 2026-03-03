"""Interactive receiver console -- arrow-key menu-driven receiver interface.

Launches with ``hdmi-receiver`` and provides an interactive menu for all
receiver operations: receive file, calibrate signal, detect capture card,
view last transfer stats, and settings.

Usage::

    hdmi-receiver
"""

from __future__ import annotations

import argparse

from InquirerPy import inquirer
from InquirerPy.separator import Separator

from hdmi_exfil.core.config import PROFILES, ResolutionProfile
from hdmi_exfil.receiver.cli.receive import run_receive


# ------------------------------------------------------------------
# Capture device detection
# ------------------------------------------------------------------


def _detect_devices(max_index: int = 10) -> list[dict]:
    """Probe capture device indices and return available devices.

    Probes cv2.VideoCapture(i) for indices 0 through max_index-1.
    Returns a list of dicts with keys: index, width, height, fps.
    """
    import cv2

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


# ------------------------------------------------------------------
# Menu constants
# ------------------------------------------------------------------

_MENU_RECEIVE = "Receive file"
_MENU_CALIBRATE = "Calibrate signal"
_MENU_DETECT = "Detect capture card"
_MENU_STATS = "Last transfer stats"
_MENU_SETTINGS = "Settings"
_MENU_QUIT = "Quit"


def _show_main_menu() -> str:
    """Display the main menu and return the selected action string."""
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


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------


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


def _action_calibrate() -> None:
    """Capture and analyze calibration pattern via existing calibrate recv command."""
    # Detect devices first
    print("Detecting capture devices...")
    devices = _detect_devices()
    if not devices:
        print("No capture devices found. Connect a capture card and try again.")
        return

    if len(devices) == 1:
        source_idx = devices[0]["index"]
        d = devices[0]
        print(f"  Using device {source_idx}: {d['width']}x{d['height']} @ {d['fps']:.0f} FPS")
    else:
        device_choices = [
            {
                "name": f"Device {d['index']}: {d['width']}x{d['height']} @ {d['fps']:.0f} FPS",
                "value": d["index"],
            }
            for d in devices
        ]
        source_idx = inquirer.select(
            message="Capture device:",
            choices=device_choices,
        ).execute()

    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=list(PROFILES.keys()),
        default="speed",
    ).execute()
    profile = PROFILES[profile_name]

    # Import and call the calibrate recv function
    from hdmi_exfil.receiver.cli.calibrate import _cmd_recv

    # Build a minimal args namespace (calibrate recv needs source and frames)
    args = argparse.Namespace(source=str(source_idx), frames=10, output_dir=None)
    _cmd_recv(profile, args)


def _action_detect() -> None:
    """Detect and display available capture devices."""
    print("\nDetecting capture devices...")
    devices = _detect_devices()
    if not devices:
        print("No capture devices found.")
    else:
        print(f"Found {len(devices)} device(s):")
        for d in devices:
            print(f"  Device {d['index']}: {d['width']}x{d['height']} @ {d['fps']:.0f} FPS")
    print()


# Module-level state for last transfer (in-memory only, lost on exit)
_last_transfer: dict | None = None


def _action_stats() -> None:
    """Display statistics from the last completed transfer."""
    if _last_transfer is None:
        print("\nNo transfer completed yet.")
        print()
        return
    print("\nLast Transfer:")
    for key, value in _last_transfer.items():
        print(f"  {key}: {value}")
    print()


def _action_settings() -> None:
    """Display current configuration settings (informational only)."""
    print("\nCurrent Settings:")
    print(f"  Default profile:   speed")
    print(f"  Default output:    received_files")
    print(f"  Threaded capture:  enabled")
    print(f"  Buffer size:       16 frames")
    print(f"  Receive mode:      auto-detect")
    print()
    print("Settings persistence is not yet available.")
    print("Use CLI flags with hdmi-recv for custom values.")
    print()


# ------------------------------------------------------------------
# Dispatch and main loop
# ------------------------------------------------------------------

_DISPATCH = {
    _MENU_RECEIVE: _action_receive,
    _MENU_CALIBRATE: _action_calibrate,
    _MENU_DETECT: _action_detect,
    _MENU_STATS: _action_stats,
    _MENU_SETTINGS: _action_settings,
}


def main() -> None:
    """Entry point for ``hdmi-receiver`` interactive console."""
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
