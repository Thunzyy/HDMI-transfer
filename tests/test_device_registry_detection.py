from __future__ import annotations

import subprocess
import sys

import cv2
import numpy as np


class _FakeCap:
    def __init__(
        self,
        *,
        width: int = 1920,
        height: int = 1080,
        fps: float = 60.0,
        frames: list[np.ndarray] | None = None,
        opened: bool = True,
    ) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._frames = list(frames or [])
        self._opened = opened

    def isOpened(self) -> bool:
        return self._opened

    def set(self, prop: int, value: float) -> None:
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            self._width = int(value)
        elif prop == cv2.CAP_PROP_FRAME_HEIGHT:
            self._height = int(value)
        elif prop == cv2.CAP_PROP_FPS:
            self._fps = float(value)

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._width)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._height)
        if prop == cv2.CAP_PROP_FPS:
            return float(self._fps)
        return 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self._frames:
            return False, None
        return True, self._frames.pop(0)

    def release(self) -> None:
        self._opened = False


def _install_fakes(monkeypatch, *, ffmpeg_names, dshow_caps, msmf_caps=None):
    """Fake ffmpeg's DirectShow listing and the OpenCV backends."""
    import hdmi_transfer.receiver.capture.source as source

    monkeypatch.setattr(sys, "platform", "win32")
    listing = "\n".join(f'[dshow] "{name}" (video)' for name in ffmpeg_names)
    listing += '\n[dshow] "OBS Virtual Camera" (none)\n[dshow] "Mic (USB)" (audio)'

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr=listing,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    msmf_calls: list[int] = []

    def fake_open_capture(index, backend, width, height, fps):
        msmf_calls.append(index)
        factory = (msmf_caps or {}).get(index)
        return factory() if factory else None

    class FakeVideoCapture:
        def __init__(self, index, backend):
            if backend != cv2.CAP_DSHOW:
                raise AssertionError("Windows detection must probe DirectShow")
            factory = dshow_caps.get(index)
            self._cap = factory() if factory else _FakeCap(opened=False)

        def isOpened(self):
            return self._cap.isOpened()

        def set(self, prop, value):
            self._cap.set(prop, value)

        def get(self, prop):
            return self._cap.get(prop)

        def read(self):
            return self._cap.read()

        def release(self):
            self._cap.release()

    monkeypatch.setattr(source, "open_capture", fake_open_capture)
    monkeypatch.setattr(cv2, "VideoCapture", FakeVideoCapture)
    return msmf_calls


def _frames(value, n=10):
    return [np.full((8, 8, 3), value, dtype=np.uint8) for _ in range(n)]


def test_detect_devices_names_follow_directshow_order(monkeypatch):
    """Regression: MSMF and DirectShow orders differ, names must not be swapped.

    Real layout seen on PCFIXE: DirectShow = Elgato, Iriun, eMeet, NVIDIA
    while MSMF = eMeet, Elgato, Iriun. The old brightness matching produced
    two "Elgato 4K X" entries, one of which opened the eMeet/Iriun camera.
    """
    from hdmi_transfer.adapters.capture.device_registry import detect_devices

    msmf_calls = _install_fakes(
        monkeypatch,
        ffmpeg_names=[
            "Elgato 4K X", "Iriun Webcam", "HD Webcam eMeet C960",
            "Camera (NVIDIA Broadcast)",
        ],
        dshow_caps={
            0: lambda: _FakeCap(frames=_frames(31)),
            1: lambda: _FakeCap(frames=_frames(1)),
            2: lambda: _FakeCap(frames=_frames(2)),
            3: lambda: _FakeCap(frames=_frames(0)),
        },
        msmf_caps={
            0: lambda: _FakeCap(frames=_frames(2)),
            1: lambda: _FakeCap(frames=_frames(31)),
            2: lambda: _FakeCap(frames=_frames(1)),
        },
    )

    devices = detect_devices(max_index=6)

    assert [d["name"] for d in devices] == [
        "Elgato 4K X", "Iriun Webcam", "HD Webcam eMeet C960",
        "Camera (NVIDIA Broadcast)",
    ]
    for position, device in enumerate(devices):
        assert device["index"] == position
        assert device["dshow_index"] == position
        assert device["backend"] == int(cv2.CAP_DSHOW)
    assert devices[0]["prefer_dshow"] is True
    assert devices[0]["ffmpeg_dshow_name"] == "Elgato 4K X"
    assert devices[1]["ffmpeg_dshow_name"] is None
    assert msmf_calls == []


def test_detect_devices_keeps_capture_card_waiting_for_signal(monkeypatch):
    """A capture card with no HDMI signal returns black frames: still listed."""
    from hdmi_transfer.adapters.capture.device_registry import detect_devices

    _install_fakes(
        monkeypatch,
        ffmpeg_names=["Iriun Webcam", "Elgato 4K X"],
        dshow_caps={
            0: lambda: _FakeCap(frames=_frames(120)),
            1: lambda: _FakeCap(fps=0.0, frames=_frames(0)),
        },
    )

    devices = detect_devices(max_index=4)

    elgato = devices[1]
    assert elgato["name"] == "Elgato 4K X"
    assert elgato["dshow_index"] == 1
    assert elgato["fps"] == 60.0
    assert elgato["width"] == 1920 and elgato["height"] == 1080


def test_detect_devices_skips_unopenable_directshow_entries(monkeypatch):
    from hdmi_transfer.adapters.capture.device_registry import detect_devices

    _install_fakes(
        monkeypatch,
        ffmpeg_names=["Busy Camera", "Elgato 4K X"],
        dshow_caps={1: lambda: _FakeCap(frames=_frames(50))},
    )

    devices = detect_devices(max_index=4)

    assert devices == [{
        "index": 1,
        "name": "Elgato 4K X",
        "width": 1920,
        "height": 1080,
        "fps": 60.0,
        "backend": int(cv2.CAP_DSHOW),
        "dshow_index": 1,
        "prefer_dshow": True,
        "ffmpeg_dshow_name": "Elgato 4K X",
    }]


def test_detect_devices_without_names_uses_generic_labels(monkeypatch):
    from hdmi_transfer.adapters.capture.device_registry import detect_devices

    _install_fakes(
        monkeypatch,
        ffmpeg_names=[],
        dshow_caps={0: lambda: _FakeCap(frames=_frames(50))},
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )

    devices = detect_devices(max_index=2)

    assert devices[0]["name"] == "Camera 0"
    assert devices[0]["ffmpeg_dshow_name"] is None


def test_registry_ignores_unversioned_cache_from_old_detection(tmp_path):
    """Old caches paired MSMF indices with DirectShow names: never reuse them."""
    import json

    from hdmi_transfer.adapters.capture.device_registry import DeviceRegistry

    cache = tmp_path / "devices.json"
    cache.write_text(json.dumps([{"index": 0, "name": "Elgato 4K X", "backend": 1400}]))

    assert DeviceRegistry(cache).list_devices() == []


def test_registry_round_trips_current_cache(tmp_path):
    from hdmi_transfer.adapters.capture.device_registry import DeviceRegistry

    cache = tmp_path / "devices.json"
    devices = [{"index": 0, "name": "Elgato 4K X", "backend": 700}]
    DeviceRegistry(cache).replace(devices)

    assert DeviceRegistry(cache).list_devices() == devices
