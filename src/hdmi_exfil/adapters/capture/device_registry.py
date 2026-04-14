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
    capture_card_names = [name for name in dshow_names if _is_capture_card_name(name)]

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
            stats = _probe_stream_stats(cap, np, cv2)
            cap.release()
            msmf_devices.append({
                "msmf_index": index,
                "width": width,
                "height": height,
                "fps": fps,
                "stats": stats,
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
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            stats = _probe_stream_stats(cap, np, cv2)
            cap.release()
            name = (
                dshow_names[index]
                if index < len(dshow_names)
                else f"Device {index}"
            )
            dshow_frames[index] = {
                "name": name,
                "width": width,
                "height": height,
                "fps": fps,
                "stats": stats,
            }

    dshow_zero = {
        index: info["name"]
        for index, info in dshow_frames.items()
        if info["stats"]["is_zero"]
    }
    dshow_name_to_index = {
        _normalize_name(str(info["name"])): index
        for index, info in dshow_frames.items()
    }
    dshow_nonzero = {
        index: info
        for index, info in dshow_frames.items()
        if not info["stats"]["is_zero"]
    }

    devices = []
    used_dshow: set[int] = set()
    used_names: set[str] = set()

    for msmf in msmf_devices:
        msmf_index = msmf["msmf_index"]
        msmf_stats = msmf["stats"]
        msmf_brightness = float(msmf_stats["brightness"])
        name = None
        matched_dshow = None

        similar_dshow = _find_similar_dshow_match(
            msmf_stats=msmf_stats,
            dshow_frames=dshow_frames,
            used_dshow=used_dshow,
        )
        if similar_dshow is not None:
            name = str(dshow_frames[similar_dshow]["name"])
            matched_dshow = similar_dshow
            used_dshow.add(similar_dshow)

        if name is None and msmf_brightness <= 10:
            candidate_name = _claim_unused_name(capture_card_names, used_names)
            if candidate_name is not None:
                name = candidate_name

        if name is None and msmf_brightness > 10:
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
                    break
            if name is None:
                best_dshow = None
                best_diff = float("inf")
                for dshow_index, info in dshow_nonzero.items():
                    if dshow_index in used_dshow:
                        continue
                    diff = abs(float(info["stats"]["brightness"]) - msmf_brightness)
                    if diff < best_diff:
                        best_diff = diff
                        best_dshow = dshow_index
                if best_dshow is not None:
                    name = str(dshow_nonzero[best_dshow]["name"])
                    matched_dshow = best_dshow
                    used_dshow.add(best_dshow)
        elif name is None:
            for dshow_index, info in dshow_nonzero.items():
                if dshow_index in used_dshow:
                    continue
                name = str(info["name"])
                matched_dshow = dshow_index
                used_dshow.add(dshow_index)
                break

        if name is None:
            for dshow_index, info in dshow_frames.items():
                if dshow_index not in used_dshow:
                    name = str(info["name"])
                    matched_dshow = dshow_index
                    used_dshow.add(dshow_index)
                    break

        if name is None:
            name = f"Device {msmf_index}"
        used_names.add(_normalize_name(name))

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
                dshow_info = dshow_frames[matched_dshow]
                width = int(dshow_info["width"])
                height = int(dshow_info["height"])
                fps = float(dshow_info["fps"])
                dshow_index = matched_dshow
                prefer_dshow = _should_prefer_dshow(
                    name=name,
                    msmf_stats=msmf_stats,
                    dshow_stats=dshow_info["stats"],
                )
                if prefer_dshow:
                    if width > 0 and height > 0:
                        out_width = width
                        out_height = height
                    if fps > 0:
                        out_fps = fps
        elif _is_capture_card_name(name):
            named_dshow = dshow_name_to_index.get(_normalize_name(name))
            if named_dshow is not None:
                dshow_info = dshow_frames[named_dshow]
                if not _is_low_signal_stats(dshow_info["stats"]):
                    dshow_index = named_dshow
                    prefer_dshow = _should_prefer_dshow(
                        name=name,
                        msmf_stats=msmf_stats,
                        dshow_stats=dshow_info["stats"],
                    )
                    if prefer_dshow:
                        width = int(dshow_info["width"])
                        height = int(dshow_info["height"])
                        fps = float(dshow_info["fps"])
                        if width > 0 and height > 0:
                            out_width = width
                            out_height = height
                        if fps > 0:
                            out_fps = fps
            if not prefer_dshow:
                prefer_dshow = True

        devices.append({
            "index": msmf_index,
            "name": name,
            "width": out_width,
            "height": out_height,
            "fps": out_fps,
            "backend": int(cv2.CAP_MSMF),
            "dshow_index": dshow_index,
            "prefer_dshow": prefer_dshow,
            "ffmpeg_dshow_name": name if _is_capture_card_name(name) else None,
        })

    next_index = (max((int(device["index"]) for device in devices), default=-1) + 1)
    for dshow_index, info in sorted(dshow_frames.items()):
        preferred_name = str(info["name"])
        width = int(info["width"])
        height = int(info["height"])
        fps = float(info["fps"])
        if dshow_index in dshow_zero:
            capture_name = next(
                (
                    candidate
                    for candidate in capture_card_names
                    if _normalize_name(candidate) not in used_names
                ),
                None,
            )
            if capture_name is not None:
                preferred_name = capture_name

        normalized = _normalize_name(preferred_name)
        if dshow_index in used_dshow or normalized in used_names:
            continue

        devices.append({
            "index": next_index,
            "name": preferred_name,
            "width": width if width > 0 else 1920,
            "height": height if height > 0 else 1080,
            "fps": fps if fps > 0 else 60.0,
            "backend": int(cv2.CAP_DSHOW),
            "dshow_index": dshow_index,
            "prefer_dshow": _is_capture_card_name(preferred_name),
            "ffmpeg_dshow_name": (
                preferred_name if _is_capture_card_name(preferred_name) else None
            ),
        })
        used_names.add(normalized)
        next_index += 1

    return devices


def _probe_stream_stats(cap, np, cv2) -> dict[str, float | bool | object]:
    brightness = 0.0
    max_value = 0
    nonzero_ratio = 0.0
    motion = 0.0
    frame_means: list[float] = []
    got_frame = False
    previous_sample = None
    texture_std = 0.0
    fingerprint = None

    for _ in range(10):
        ret, frame = cap.read()
        if not ret or not isinstance(frame, np.ndarray):
            continue

        got_frame = True
        sample = frame[::16, ::16]
        gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        brightness = max(brightness, float(gray.mean()))
        max_value = max(max_value, int(sample.max()))
        nonzero_ratio = max(
            nonzero_ratio,
            float(np.count_nonzero(sample)) / float(sample.size),
        )
        frame_means.append(float(gray.mean()))
        texture_std = max(texture_std, float(gray.std()))
        fingerprint = cv2.resize(
            gray,
            (32, 18),
            interpolation=cv2.INTER_AREA,
        ).astype(np.float32) / 255.0

        sample_i16 = sample.astype(np.int16, copy=False)
        if previous_sample is not None:
            motion = max(
                motion,
                float(np.abs(sample_i16 - previous_sample).mean()),
            )
        previous_sample = sample_i16

    frame_std = float(np.std(frame_means)) if len(frame_means) > 1 else 0.0
    signal_score = 0.0
    signal_score += min(max_value / 64.0, 1.0)
    signal_score += min(nonzero_ratio * 4.0, 1.0)
    signal_score += min(brightness / 32.0, 1.0)
    signal_score += min(motion / 12.0, 1.0)
    signal_score += min(frame_std / 8.0, 1.0)

    return {
        "got_frame": got_frame,
        "brightness": brightness,
        "max_value": float(max_value),
        "nonzero_ratio": nonzero_ratio,
        "motion": motion,
        "frame_std": frame_std,
        "texture_std": texture_std,
        "signal_score": signal_score,
        "is_zero": max_value == 0,
        "fingerprint": fingerprint,
    }


def _should_prefer_dshow(
    *,
    name: str,
    msmf_stats: dict[str, float | bool],
    dshow_stats: dict[str, float | bool],
) -> bool:
    if not _is_capture_card_name(name):
        return False

    if not bool(dshow_stats.get("got_frame")):
        return False

    dshow_signal = float(dshow_stats.get("signal_score", 0.0))
    msmf_signal = float(msmf_stats.get("signal_score", 0.0))

    if dshow_signal >= 1.0 and dshow_signal + 0.75 >= msmf_signal:
        return True
    if msmf_signal >= 1.0 and dshow_signal + 0.5 < msmf_signal:
        return False
    return dshow_signal >= msmf_signal


def _find_similar_dshow_match(
    *,
    msmf_stats: dict[str, float | bool | object],
    dshow_frames: dict[int, dict[str, object]],
    used_dshow: set[int],
) -> int | None:
    if _is_low_signal_stats(msmf_stats):
        return None

    candidates: list[tuple[float, int]] = []
    for dshow_index, info in dshow_frames.items():
        if dshow_index in used_dshow:
            continue
        if _is_low_signal_stats(info["stats"]):
            continue
        score = _frame_similarity_score(msmf_stats, info["stats"])
        if score is None:
            continue
        candidates.append((score, dshow_index))

    if not candidates:
        return None

    candidates.sort()
    best_score, best_index = candidates[0]
    second_score = candidates[1][0] if len(candidates) > 1 else float("inf")

    if best_score <= 0.08 and second_score >= (best_score + 0.08):
        return best_index
    return None


def _frame_similarity_score(
    a_stats: dict[str, float | bool | object],
    b_stats: dict[str, float | bool | object],
) -> float | None:
    import numpy as np

    a_fp = a_stats.get("fingerprint")
    b_fp = b_stats.get("fingerprint")
    if not isinstance(a_fp, np.ndarray) or not isinstance(b_fp, np.ndarray):
        return None

    score = float(np.mean(np.abs(a_fp - b_fp)))
    score += abs(float(a_stats.get("max_value", 0.0)) - float(b_stats.get("max_value", 0.0))) / 255.0 * 0.8
    score += abs(float(a_stats.get("nonzero_ratio", 0.0)) - float(b_stats.get("nonzero_ratio", 0.0))) * 0.6
    score += abs(float(a_stats.get("texture_std", 0.0)) - float(b_stats.get("texture_std", 0.0))) / 64.0 * 0.6
    score += abs(float(a_stats.get("brightness", 0.0)) - float(b_stats.get("brightness", 0.0))) / 255.0 * 0.4
    return score


def _is_low_signal_stats(stats: dict[str, float | bool | object]) -> bool:
    if bool(stats.get("is_zero")):
        return True
    return float(stats.get("signal_score", 0.0)) < 0.5


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


def _claim_unused_name(candidates: list[str], used_names: set[str]) -> str | None:
    for candidate in candidates:
        normalized = _normalize_name(candidate)
        if normalized not in used_names:
            used_names.add(normalized)
            return candidate
    return None


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
