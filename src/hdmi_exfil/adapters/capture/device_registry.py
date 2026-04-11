"""Device detection and cache management for capture hardware."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Callable


DeviceDetector = Callable[[], list[dict]]


class DeviceRegistry:
    """Thread-safe in-memory and on-disk cache for detected capture devices."""

    def __init__(self, cache_file: Path) -> None:
        self._cache_file = cache_file
        self._devices: list[dict] = self._load_disk_cache() or []
        self._lock = threading.Lock()
        self._open_lock = threading.Lock()

    @property
    def open_lock(self) -> threading.Lock:
        return self._open_lock

    def list_devices(self) -> list[dict]:
        with self._lock:
            return list(self._devices)

    def replace(self, devices: list[dict]) -> list[dict]:
        with self._lock:
            self._devices = list(devices)
        self._save_disk_cache(devices)
        return devices

    def detect(self, detector: DeviceDetector) -> list[dict]:
        with self._open_lock:
            devices = detector()
        return self.replace(devices)

    def get_backend(self, device_idx: int) -> int | None:
        with self._lock:
            for device in self._devices:
                if device["index"] == device_idx:
                    return device.get("backend")
        return None

    def get_device(self, device_idx: int) -> dict | None:
        with self._lock:
            for device in self._devices:
                if device["index"] == device_idx:
                    return dict(device)
        return None

    def _load_disk_cache(self) -> list[dict] | None:
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text())
                if isinstance(data, list) and data:
                    return data
        except Exception:
            pass
        return None

    def _save_disk_cache(self, devices: list[dict]) -> None:
        try:
            self._cache_file.write_text(json.dumps(devices))
        except Exception:
            pass


def detect_devices(max_index: int = 10) -> list[dict]:
    """Probe capture device indices and return available devices with names."""
    import contextlib
    import os
    import re
    import subprocess
    import sys

    import cv2
    import numpy as np

    from hdmi_exfil.receiver.capture.source import _get_backends, open_capture

    @contextlib.contextmanager
    def suppress_stderr():
        old_fd = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        try:
            yield
        finally:
            os.dup2(old_fd, 2)
            os.close(old_fd)
            os.close(devnull)

    def get_device_names_ffmpeg() -> list[str] | None:
        try:
            result = subprocess.run(
                ["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            names = []
            for line in result.stderr.split("\n"):
                match = re.search(r'"(.+?)"\s*\(video\)', line)
                if match:
                    names.append(match.group(1))
            return names if names else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def get_device_names_wmi() -> list[str] | None:
        if sys.platform != "win32":
            return None
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-PnpDevice -Class Camera,Image -Status OK "
                    "| Select-Object -ExpandProperty FriendlyName",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return [
                    name.strip()
                    for name in result.stdout.strip().split("\n")
                    if name.strip()
                ]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    dshow_names = get_device_names_ffmpeg() or get_device_names_wmi() or []

    if sys.platform != "win32":
        for backend in _get_backends():
            devices = []
            with suppress_stderr():
                for index in range(max_index):
                    cap = open_capture(index, backend, 1920, 1080, 60)
                    if cap is None:
                        continue
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    cap.release()
                    name = (
                        dshow_names[index]
                        if index < len(dshow_names)
                        else f"Device {index}"
                    )
                    devices.append({
                        "index": index,
                        "name": name,
                        "width": width,
                        "height": height,
                        "fps": fps,
                        "backend": int(backend),
                    })
            if devices:
                return devices
        return []

    msmf_devices = []
    with suppress_stderr():
        for index in range(max_index):
            cap = open_capture(index, cv2.CAP_MSMF, 1920, 1080, 60)
            if cap is None:
                continue
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            brightness = 0.0
            for _ in range(10):
                ret, frame = cap.read()
                if ret and isinstance(frame, np.ndarray):
                    brightness = max(brightness, float(frame.mean()))
            cap.release()
            msmf_devices.append({
                "msmf_index": index,
                "width": width,
                "height": height,
                "fps": fps,
                "brightness": brightness,
            })

    if not msmf_devices:
        return []

    dshow_frames = {}
    with suppress_stderr():
        for index in range(max_index):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            best_brightness = -1.0
            is_zero = True
            got_frame = False
            for _ in range(10):
                ret, frame = cap.read()
                if not ret or not isinstance(frame, np.ndarray):
                    continue
                got_frame = True
                best_brightness = max(best_brightness, float(frame.mean()))
                if int(frame.max()) > 0:
                    is_zero = False
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            name = (
                dshow_names[index]
                if index < len(dshow_names)
                else f"Device {index}"
            )
            if not got_frame:
                best_brightness = -1.0
                is_zero = True
            dshow_frames[index] = (
                name,
                best_brightness,
                is_zero,
                width,
                height,
                fps,
            )

    dshow_zero = {
        index: name
        for index, (name, _, is_zero, _, _, _) in dshow_frames.items()
        if is_zero
    }
    dshow_nonzero = {
        index: (name, brightness, width, height, fps)
        for index, (name, brightness, is_zero, width, height, fps) in dshow_frames.items()
        if not is_zero
    }

    devices = []
    used_dshow: set[int] = set()

    for msmf in msmf_devices:
        msmf_index = msmf["msmf_index"]
        msmf_brightness = msmf["brightness"]
        name = None
        matched_dshow = None

        if msmf_brightness > 10:
            for dshow_index, dshow_name in dshow_zero.items():
                if dshow_index in used_dshow:
                    continue
                lower = dshow_name.lower()
                if any(
                    keyword in lower
                    for keyword in (
                        "elgato",
                        "avermedia",
                        "capture",
                        "hdmi",
                        "cam link",
                        "magewell",
                        "blackmagic",
                        "4k",
                    )
                ):
                    name = dshow_name
                    matched_dshow = dshow_index
                    used_dshow.add(dshow_index)
                    break
            if name is None:
                best_dshow = None
                best_diff = float("inf")
                for dshow_index, (dshow_name, brightness, _, _, _) in dshow_nonzero.items():
                    if dshow_index in used_dshow:
                        continue
                    diff = abs(brightness - msmf_brightness)
                    if diff < best_diff:
                        best_diff = diff
                        best_dshow = dshow_index
                if best_dshow is not None:
                    name = dshow_nonzero[best_dshow][0]
                    matched_dshow = best_dshow
                    used_dshow.add(best_dshow)
        else:
            for dshow_index, (dshow_name, _, _, _, _) in dshow_nonzero.items():
                if dshow_index in used_dshow:
                    continue
                name = dshow_name
                matched_dshow = dshow_index
                used_dshow.add(dshow_index)
                break

        if name is None:
            for dshow_index, (dshow_name, _, _, _, _, _) in dshow_frames.items():
                if dshow_index not in used_dshow:
                    name = dshow_name
                    matched_dshow = dshow_index
                    used_dshow.add(dshow_index)
                    break

        if name is None:
            name = f"Device {msmf_index}"

        out_width = msmf["width"]
        out_height = msmf["height"]
        out_fps = msmf["fps"]
        dshow_index = None
        prefer_dshow = False

        if matched_dshow is not None:
            lower = name.lower()
            is_capture_card = any(
                keyword in lower
                for keyword in (
                    "elgato",
                    "avermedia",
                    "capture",
                    "hdmi",
                    "cam link",
                    "magewell",
                    "blackmagic",
                    "4k",
                )
            )
            if is_capture_card and matched_dshow in dshow_frames:
                _, _, is_zero, width, height, fps = dshow_frames[matched_dshow]
                if not is_zero:
                    dshow_index = matched_dshow
                    prefer_dshow = True
                    if width > 0 and height > 0:
                        out_width = width
                        out_height = height
                    if fps > 0:
                        out_fps = fps

        devices.append({
            "index": msmf_index,
            "name": name,
            "width": out_width,
            "height": out_height,
            "fps": out_fps,
            "backend": int(cv2.CAP_MSMF),
            "dshow_index": dshow_index,
            "prefer_dshow": prefer_dshow,
        })

    return devices
