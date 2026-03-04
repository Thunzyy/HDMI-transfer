"""Interactive receiver console -- arrow-key menu-driven receiver interface.

Launches with ``hdmi-receiver`` and provides an interactive menu for all
receiver operations: receive file, calibrate signal, detect capture card,
view last transfer stats, and settings.

Usage::

    hdmi-receiver
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import subprocess
import sys

from InquirerPy import inquirer
from InquirerPy.separator import Separator

from hdmi_exfil.core.config import PROFILES, ResolutionProfile
from hdmi_exfil.core import settings
from hdmi_exfil.receiver.cli.receive import run_receive


# ------------------------------------------------------------------
# Capture device detection
# ------------------------------------------------------------------


@contextlib.contextmanager
def _suppress_stderr():
    """Redirect OS-level stderr to devnull to hide noisy driver logs."""
    old_fd = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(old_fd, 2)
        os.close(old_fd)
        os.close(devnull)


def _get_device_names_ffmpeg() -> list[str] | None:
    """Get DirectShow video device names via ffmpeg (order matches OpenCV indices)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=10,
        )
        names = []
        for line in result.stderr.split("\n"):
            m = re.search(r'"(.+?)"\s*\(video\)', line)
            if m:
                names.append(m.group(1))
        return names if names else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _get_device_names_wmi() -> list[str] | None:
    """Get video device names via PowerShell/WMI (Windows fallback)."""
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Camera,Image -Status OK "
             "| Select-Object -ExpandProperty FriendlyName"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [n.strip() for n in result.stdout.strip().split("\n") if n.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _detect_devices(max_index: int = 10) -> list[dict]:
    """Probe capture device indices and return available devices with names.

    On Windows, DSHOW and MSMF may have different device counts and
    ordering.  This function detects MSMF devices (used for capture),
    then identifies each by reading a test frame and cross-referencing
    with DSHOW names using per-device DSHOW probing.

    Returns a list of dicts with keys: index, name, width, height, fps, backend.
    """
    import cv2
    import numpy as np

    from hdmi_exfil.receiver.capture.source import _get_backends, _try_open

    dshow_names = _get_device_names_ffmpeg() or _get_device_names_wmi() or []

    if sys.platform != "win32":
        backends = _get_backends()
        for backend in backends:
            devices = []
            with _suppress_stderr():
                for i in range(max_index):
                    cap = _try_open(i, backend, 1920, 1080, 60)
                    if cap is None:
                        continue
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    cap.release()
                    name = dshow_names[i] if i < len(dshow_names) else f"Device {i}"
                    devices.append({
                        "index": i, "name": name,
                        "width": w, "height": h, "fps": fps,
                        "backend": int(backend),
                    })
            if devices:
                return devices
        return []

    # ── Windows: DSHOW/MSMF may have different device counts & order ──
    # Strategy: for each MSMF device, try ALL DSHOW indices to find which
    # DSHOW device refers to the same physical hardware (by exclusion test).

    # Step 1: Collect MSMF devices with frame brightness as fingerprint
    msmf_devices = []
    with _suppress_stderr():
        for i in range(max_index):
            cap = _try_open(i, cv2.CAP_MSMF, 1920, 1080, 60)
            if cap is None:
                continue
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            # Read several test frames (first frames may be black/buffered)
            brightness = 0.0
            for _ in range(10):
                ret, frame = cap.read()
                if ret and isinstance(frame, np.ndarray):
                    b = float(frame.mean())
                    if b > brightness:
                        brightness = b
            cap.release()
            msmf_devices.append({
                "msmf_index": i, "width": w, "height": h,
                "fps": fps, "brightness": brightness,
            })

    if not msmf_devices:
        return []

    # Step 2: Match MSMF devices to DSHOW names.
    # DSHOW and MSMF may have different device counts (e.g. NVIDIA
    # Broadcast only in DSHOW). We match by reading a DSHOW frame for
    # each index and comparing brightness/zero patterns to MSMF frames.
    dshow_frames = {}  # dshow_index -> (name, brightness, is_zero)
    with _suppress_stderr():
        for i in range(max_index):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if not cap.isOpened():
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            ret, frame = cap.read()
            cap.release()
            name = dshow_names[i] if i < len(dshow_names) else f"Device {i}"
            if ret and isinstance(frame, np.ndarray):
                b = float(frame.mean())
                is_zero = int(frame.max()) == 0
            else:
                b = -1.0
                is_zero = True
            dshow_frames[i] = (name, b, is_zero)

    # Classify DSHOW devices: zero-frame devices are candidates for
    # capture cards (Elgato DSHOW bug) or virtual cams (NVIDIA Broadcast).
    # Non-zero DSHOW devices are webcams we can match by brightness.
    dshow_zero = {i: n for i, (n, b, z) in dshow_frames.items() if z}
    dshow_nonzero = {i: (n, b) for i, (n, b, z) in dshow_frames.items() if not z}

    # Match MSMF devices to DSHOW names
    devices = []
    used_dshow = set()

    for md in msmf_devices:
        mi = md["msmf_index"]
        mb = md["brightness"]
        name = None

        if mb > 10:
            # MSMF device has real signal. If it's a capture card, the
            # DSHOW version would return all-zero frames (known Elgato bug).
            # Find a DSHOW zero-frame device with a capture-card name.
            for di, dn in dshow_zero.items():
                if di in used_dshow:
                    continue
                nl = dn.lower()
                if any(k in nl for k in ("elgato", "avermedia", "capture",
                                          "hdmi", "cam link", "magewell",
                                          "blackmagic", "4k")):
                    name = dn
                    used_dshow.add(di)
                    break
            if name is None:
                # Could be a webcam with signal — match to non-zero DSHOW
                best_di = None
                best_diff = float("inf")
                for di, (dn, db) in dshow_nonzero.items():
                    if di in used_dshow:
                        continue
                    diff = abs(db - mb)
                    if diff < best_diff:
                        best_diff = diff
                        best_di = di
                if best_di is not None:
                    name = dshow_nonzero[best_di][0]
                    used_dshow.add(best_di)
        else:
            # MSMF device is dark/black — match to non-zero DSHOW webcam
            # (webcam with lens cap appears black via MSMF but may read
            # via DSHOW), or to remaining DSHOW devices.
            for di, (dn, db) in dshow_nonzero.items():
                if di in used_dshow:
                    continue
                name = dn
                used_dshow.add(di)
                break

        if name is None:
            # Use any remaining DSHOW name
            for di, (dn, _, _) in dshow_frames.items():
                if di not in used_dshow:
                    name = dn
                    used_dshow.add(di)
                    break

        if name is None:
            name = f"Device {mi}"

        devices.append({
            "index": mi, "name": name,
            "width": md["width"], "height": md["height"],
            "fps": md["fps"], "backend": int(cv2.CAP_MSMF),
        })

    return devices


# ------------------------------------------------------------------
# Device selection helper (uses saved default)
# ------------------------------------------------------------------


def _pick_device(devices: list[dict]) -> int:
    """Select a capture device, auto-selecting the saved default if it matches."""
    saved_name = settings.get("receiver", "device_name")
    if saved_name:
        for d in devices:
            if d["name"] == saved_name:
                print(f"  Using saved device: {d['name']} "
                      f"({d['width']}x{d['height']} @ {d['fps']:.0f} FPS)")
                return d["index"]

    if len(devices) == 1:
        d = devices[0]
        print(f"  Using: {d['name']} ({d['width']}x{d['height']} @ {d['fps']:.0f} FPS)")
        return d["index"]

    device_choices = [
        {
            "name": f"{d['name']} ({d['width']}x{d['height']} @ {d['fps']:.0f} FPS)",
            "value": d["index"],
        }
        for d in devices
    ]
    return inquirer.select(message="Capture device:", choices=device_choices).execute()


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
    """Use saved settings to start receiving immediately."""
    cfg = settings.load()["receiver"]

    profile_name = cfg.get("profile", "speed")
    profile = PROFILES[profile_name]
    source = None

    # Fast path: try saved device directly (skip full detection scan)
    saved_name = cfg.get("device_name")
    saved_index = cfg.get("device_index")
    if saved_name and saved_index is not None:
        try:
            from hdmi_exfil.receiver.capture.source import CaptureSource

            with _suppress_stderr():
                cap = CaptureSource(
                    saved_index,
                    width=profile.width,
                    height=profile.height,
                    fps=profile.target_fps,
                )
            print(f"  Device: {saved_name} ({cap.actual_width}x{cap.actual_height}"
                  f" @ {cap.actual_fps:.0f} FPS)")
            cap.release()
            source = saved_index
        except Exception:
            print(f"  Saved device '{saved_name}' not available. Detecting...")

    # Slow path: full detection (no saved device, or saved device failed)
    if source is None:
        print("Detecting capture devices...")
        devices = _detect_devices()
        if not devices:
            print("No capture devices found. Connect a capture card and try again.")
            return
        source = _pick_device(devices)

    # Use saved settings directly — no prompts
    output = cfg.get("output", "received_files")
    mode = cfg.get("mode", "auto")

    print(f"  Profile: {profile_name} | Mode: {mode} | Output: {output}")
    print()

    run_receive(
        source=source,
        mode=mode,
        profile=profile,
        output=output,
    )


def _action_calibrate() -> None:
    """Capture and analyze calibration pattern via existing calibrate recv command."""
    cfg = settings.load()["receiver"]

    print("Detecting capture devices...")
    devices = _detect_devices()
    if not devices:
        print("No capture devices found. Connect a capture card and try again.")
        return
    source_idx = _pick_device(devices)

    default_profile = cfg.get("profile", "speed")
    profile_name = inquirer.select(
        message="Resolution profile:",
        choices=list(PROFILES.keys()),
        default=default_profile,
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
            print(f"  [{d['index']}] {d['name']} — {d['width']}x{d['height']} @ {d['fps']:.0f} FPS")
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
    """View and edit persistent receiver settings."""
    cfg = settings.load()["receiver"]
    print(f"\nReceiver Settings ({settings.settings_path()}):")
    print(f"  Capture device:  {cfg.get('device_name') or '(auto-detect)'}")
    print(f"  Profile:         {cfg.get('profile', 'speed')}")
    print(f"  Receive mode:    {cfg.get('mode', 'auto')}")
    print(f"  Output dir:      {cfg.get('output', 'received_files')}")
    print()

    action = inquirer.select(
        message="Edit settings?",
        choices=["Change capture device", "Change profile", "Change mode",
                 "Change output dir", "Back to menu"],
    ).execute()

    if action == "Change capture device":
        print("Detecting devices...")
        devices = _detect_devices()
        if not devices:
            print("No devices found.")
            return
        choices = [
            {"name": f"{d['name']} ({d['width']}x{d['height']})", "value": d}
            for d in devices
        ] + [{"name": "(none — always ask)", "value": None}]
        picked = inquirer.select(message="Default device:", choices=choices).execute()
        if picked is not None:
            settings.set_value("receiver", "device_name", picked["name"])
            settings.set_value("receiver", "device_index", picked["index"])
            print(f"  Saved: {picked['name']} (index {picked['index']})")
        else:
            settings.set_value("receiver", "device_name", None)
            settings.set_value("receiver", "device_index", None)
            print("  Saved: (auto-detect)")

    elif action == "Change profile":
        picked = inquirer.select(
            message="Default profile:",
            choices=list(PROFILES.keys()),
            default=cfg.get("profile", "speed"),
        ).execute()
        settings.set_value("receiver", "profile", picked)
        print(f"  Saved: profile = {picked}")

    elif action == "Change mode":
        picked = inquirer.select(
            message="Default mode:",
            choices=["auto", "sequential", "fountain"],
            default=cfg.get("mode", "auto"),
        ).execute()
        settings.set_value("receiver", "mode", picked)
        print(f"  Saved: mode = {picked}")

    elif action == "Change output dir":
        picked = inquirer.text(
            message="Default output dir:",
            default=cfg.get("output", "received_files"),
        ).execute()
        settings.set_value("receiver", "output", picked)
        print(f"  Saved: output = {picked}")
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
