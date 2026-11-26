"""Device detection and cache management for capture hardware."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Callable


DeviceDetector = Callable[[], list[dict]]

# Bump when the meaning of a cached device entry changes. Version 2: logical
# index == DirectShow index on Windows (version 1 used guessed MSMF pairs).
CACHE_VERSION = 2


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
                if (
                    isinstance(data, dict)
                    and data.get("version") == CACHE_VERSION
                    and isinstance(data.get("devices"), list)
                    and data["devices"]
                ):
                    return data["devices"]
        except Exception:
            pass
        return None

    def _save_disk_cache(self, devices: list[dict]) -> None:
        try:
            self._cache_file.write_text(
                json.dumps({"version": CACHE_VERSION, "devices": devices}),
            )
        except Exception:
            pass


def resolve_device_open_target(device: dict) -> tuple[int, int | None]:
    """Return the raw source/backend pair that should actually be opened."""
    import cv2

    ffmpeg_name = _ffmpeg_dshow_name(device)
    backend = _maybe_int(device.get("backend"))
    dshow_index = _maybe_int(device.get("dshow_index"))
    prefers_dshow = bool(device.get("prefer_dshow"))

    if dshow_index is not None and (prefers_dshow or backend == int(cv2.CAP_DSHOW)):
        return dshow_index, int(cv2.CAP_DSHOW)
    if ffmpeg_name is not None:
        return f"ffmpeg-dshow:{ffmpeg_name}", int(cv2.CAP_DSHOW)
    return int(device["index"]), backend


def list_device_open_targets(device: dict) -> list[tuple[int, int | None]]:
    """Return preferred then fallback capture targets for a logical device."""
    import cv2

    targets: list[tuple[int, int | None]] = []

    def add_target(source: int | str | None, backend: int | None) -> None:
        if source is None:
            return
        candidate = (source, backend)
        if candidate not in targets:
            targets.append(candidate)

    primary_source, primary_backend = resolve_device_open_target(device)
    add_target(primary_source, primary_backend)
    if not (
        isinstance(primary_source, str)
        and primary_source.startswith("ffmpeg-dshow:")
    ):
        add_target(_ffmpeg_target(device), int(cv2.CAP_DSHOW))
    add_target(_maybe_int(device.get("dshow_index")), int(cv2.CAP_DSHOW))
    add_target(_maybe_int(device.get("index")), _maybe_int(device.get("backend")))
    return targets


def detect_devices(max_index: int = 10) -> list[dict]:
    """Probe capture device indices and return available devices with names."""
    import contextlib
    import os
    import re
    import subprocess
    import sys

    import cv2

    from hdmi_transfer.receiver.capture.source import _get_backends, open_capture

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

    # ffmpeg lists DirectShow video devices in OpenCV's index order. WMI was
    # dropped: its order is arbitrary and it includes scanners/printers.
    dshow_names = get_device_names_ffmpeg() or []

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

    # Windows: DirectShow enumerates devices in the same order ffmpeg lists
    # them, so index i really is dshow_names[i]. MSMF uses a different order
    # with no names, and guessing the pairing from frame brightness put the
    # Elgato label on other cameras. Only DirectShow indices are used here.
    devices = []
    with suppress_stderr():
        for index in range(max_index):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            cap.set(cv2.CAP_PROP_FPS, 60)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            cap.release()
            name = (
                dshow_names[index]
                if index < len(dshow_names)
                else f"Camera {index}"
            )
            is_card = _is_capture_card_name(name)
            devices.append({
                "index": index,
                "name": name,
                "width": width if width > 0 else 1920,
                "height": height if height > 0 else 1080,
                # DirectShow often reports 0 FPS even when it streams at 60.
                "fps": fps if fps > 0 else 60.0,
                "backend": int(cv2.CAP_DSHOW),
                "dshow_index": index,
                "prefer_dshow": is_card,
                "ffmpeg_dshow_name": name if is_card else None,
            })
    return devices


def _is_capture_card_name(name: str) -> bool:
    lower = name.casefold()
    return any(
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


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _ffmpeg_dshow_name(device: dict) -> str | None:
    value = device.get("ffmpeg_dshow_name")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _ffmpeg_target(device: dict) -> str | None:
    name = _ffmpeg_dshow_name(device)
    if name is None:
        return None
    return f"ffmpeg-dshow:{name}"


def _maybe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
