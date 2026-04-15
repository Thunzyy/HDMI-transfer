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


def test_detect_devices_includes_dshow_only_capture_card(monkeypatch):
    from hdmi_transfer.adapters.capture.device_registry import detect_devices
    import hdmi_transfer.receiver.capture.source as source

    monkeypatch.setattr(sys, "platform", "win32")

    ffmpeg_listing = "\n".join([
        '[dshow] "Iriun Webcam" (video)',
        '[dshow] "Elgato 4K X" (video)',
    ])

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr=ffmpeg_listing,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    bright_frame = np.full((8, 8, 3), 200, dtype=np.uint8)
    dark_frame = np.zeros((8, 8, 3), dtype=np.uint8)

    def fake_open_capture(index, backend, width, height, fps):
        if backend != cv2.CAP_MSMF:
            raise AssertionError("expected MSMF probe")
        if index == 0:
            return _FakeCap(
                width=width,
                height=height,
                fps=fps,
                frames=[bright_frame.copy() for _ in range(10)],
            )
        return None

    class FakeVideoCapture:
        def __init__(self, index, backend):
            if backend != cv2.CAP_DSHOW:
                raise AssertionError("expected DSHOW probe")
            self._cap = {
                0: _FakeCap(
                    frames=[bright_frame.copy() for _ in range(10)],
                ),
                1: _FakeCap(
                    frames=[dark_frame.copy() for _ in range(2)]
                    + [bright_frame.copy() for _ in range(8)],
                ),
            }.get(index, _FakeCap(opened=False, frames=[]))

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

    devices = detect_devices(max_index=3)

    assert any(device["name"] == "Iriun Webcam" for device in devices)
    assert any(
        device["name"] == "Elgato 4K X"
        and device["backend"] == int(cv2.CAP_DSHOW)
        and device["dshow_index"] == 1
        and device["prefer_dshow"] is True
        for device in devices
    )


def test_detect_devices_keeps_msmf_when_matched_dshow_capture_card_is_dead(monkeypatch):
    from hdmi_transfer.adapters.capture.device_registry import detect_devices
    import hdmi_transfer.receiver.capture.source as source

    monkeypatch.setattr(sys, "platform", "win32")

    ffmpeg_listing = '[dshow] "Elgato 4K X" (video)'

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr=ffmpeg_listing,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    msmf_frames = [
        np.full((8, 8, 3), (255, 0, 0), dtype=np.uint8),
        np.full((8, 8, 3), (0, 255, 0), dtype=np.uint8),
        np.full((8, 8, 3), (255, 255, 255), dtype=np.uint8),
        np.full((8, 8, 3), (0, 0, 255), dtype=np.uint8),
    ] * 3
    black_frame = np.zeros((8, 8, 3), dtype=np.uint8)

    def fake_open_capture(index, backend, width, height, fps):
        if backend != cv2.CAP_MSMF:
            raise AssertionError("expected MSMF probe")
        if index == 0:
            return _FakeCap(
                width=width,
                height=height,
                fps=fps,
                frames=[frame.copy() for frame in msmf_frames],
            )
        return None

    class FakeVideoCapture:
        def __init__(self, index, backend):
            if backend != cv2.CAP_DSHOW:
                raise AssertionError("expected DSHOW probe")
            self._cap = {
                0: _FakeCap(
                    frames=[black_frame.copy() for _ in range(10)],
                ),
            }.get(index, _FakeCap(opened=False, frames=[]))

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

    devices = detect_devices(max_index=2)

    assert devices[0] == {
        "index": 0,
        "name": "Elgato 4K X",
        "width": 1920,
        "height": 1080,
        "fps": 60.0,
        "backend": int(cv2.CAP_MSMF),
        "dshow_index": None,
        "prefer_dshow": True,
        "ffmpeg_dshow_name": "Elgato 4K X",
    }


def test_detect_devices_matches_msmf_and_dshow_by_visual_similarity(monkeypatch):
    from hdmi_transfer.adapters.capture.device_registry import detect_devices
    import hdmi_transfer.receiver.capture.source as source

    monkeypatch.setattr(sys, "platform", "win32")

    ffmpeg_listing = "\n".join([
        '[dshow] "Iriun Webcam" (video)',
        '[dshow] "Elgato 4K X" (video)',
        '[dshow] "HD Webcam eMeet C960" (video)',
    ])

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr=ffmpeg_listing,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    iriun_frame = np.zeros((32, 32, 3), dtype=np.uint8)
    iriun_frame[10:22, 6:26] = 255

    elgato_frame = np.zeros((32, 32, 3), dtype=np.uint8)
    elgato_frame[:, :16] = (32, 160, 32)
    elgato_frame[:, 16:] = (160, 32, 32)

    emeet_frame = np.zeros((32, 32, 3), dtype=np.uint8)
    emeet_frame[::2, ::2] = (220, 180, 40)
    emeet_frame[1::2, 1::2] = (40, 90, 220)

    def fake_open_capture(index, backend, width, height, fps):
        if backend != cv2.CAP_MSMF:
            raise AssertionError("expected MSMF probe")
        frames = {
            0: elgato_frame,
            1: emeet_frame,
            2: iriun_frame,
        }.get(index)
        if frames is None:
            return None
        return _FakeCap(
            width=width,
            height=height,
            fps=fps,
            frames=[frames.copy() for _ in range(10)],
        )

    class FakeVideoCapture:
        def __init__(self, index, backend):
            if backend != cv2.CAP_DSHOW:
                raise AssertionError("expected DSHOW probe")
            frames = {
                0: iriun_frame,
                1: elgato_frame,
                2: emeet_frame,
            }.get(index)
            self._cap = (
                _FakeCap(frames=[frames.copy() for _ in range(10)])
                if frames is not None
                else _FakeCap(opened=False, frames=[])
            )

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

    devices = detect_devices(max_index=4)

    assert devices[0]["name"] == "Elgato 4K X"
    assert devices[0]["dshow_index"] == 1
    assert devices[0]["prefer_dshow"] is True
    assert devices[1]["name"] == "HD Webcam eMeet C960"
    assert devices[1]["dshow_index"] is None
    assert devices[2]["name"] == "Iriun Webcam"
    assert devices[2]["dshow_index"] is None


def test_detect_devices_recovers_capture_card_dshow_index_by_exact_name(monkeypatch):
    from hdmi_transfer.adapters.capture.device_registry import detect_devices
    import hdmi_transfer.receiver.capture.source as source

    monkeypatch.setattr(sys, "platform", "win32")

    ffmpeg_listing = '[dshow] "Elgato 4K X" (video)'

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr=ffmpeg_listing,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    msmf_frame = np.zeros((32, 32, 3), dtype=np.uint8)
    msmf_frame[:, :16] = (255, 32, 32)
    msmf_frame[:, 16:] = (32, 32, 255)

    dshow_frame = np.zeros((32, 32, 3), dtype=np.uint8)
    dshow_frame[::2, ::2] = (255, 255, 255)
    dshow_frame[1::2, 1::2] = (16, 16, 16)

    def fake_open_capture(index, backend, width, height, fps):
        if backend != cv2.CAP_MSMF:
            raise AssertionError("expected MSMF probe")
        if index != 0:
            return None
        return _FakeCap(
            width=width,
            height=height,
            fps=fps,
            frames=[msmf_frame.copy() for _ in range(10)],
        )

    class FakeVideoCapture:
        def __init__(self, index, backend):
            if backend != cv2.CAP_DSHOW:
                raise AssertionError("expected DSHOW probe")
            self._cap = (
                _FakeCap(frames=[dshow_frame.copy() for _ in range(10)])
                if index == 0
                else _FakeCap(opened=False, frames=[])
            )

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

    devices = detect_devices(max_index=2)

    assert devices[0]["name"] == "Elgato 4K X"
    assert devices[0]["dshow_index"] == 0
    assert devices[0]["prefer_dshow"] is True


def test_detect_devices_does_not_assign_capture_card_to_unmatched_zero_dshow_source(monkeypatch):
    from hdmi_transfer.adapters.capture.device_registry import detect_devices
    import hdmi_transfer.receiver.capture.source as source

    monkeypatch.setattr(sys, "platform", "win32")

    ffmpeg_listing = "\n".join([
        '[dshow] "Camera (NVIDIA Broadcast)" (video)',
        '[dshow] "Elgato 4K X" (video)',
    ])

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr=ffmpeg_listing,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    msmf_dark = np.zeros((32, 32, 3), dtype=np.uint8)
    dshow_dark = np.zeros((32, 32, 3), dtype=np.uint8)

    def fake_open_capture(index, backend, width, height, fps):
        if backend != cv2.CAP_MSMF:
            raise AssertionError("expected MSMF probe")
        if index == 0:
            return _FakeCap(
                width=width,
                height=height,
                fps=fps,
                frames=[msmf_dark.copy() for _ in range(10)],
            )
        return None

    class FakeVideoCapture:
        def __init__(self, index, backend):
            if backend != cv2.CAP_DSHOW:
                raise AssertionError("expected DSHOW probe")
            frames = {
                0: dshow_dark,
            }.get(index)
            self._cap = (
                _FakeCap(frames=[frames.copy() for _ in range(10)])
                if frames is not None
                else _FakeCap(opened=False, frames=[])
            )

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

    devices = detect_devices(max_index=3)

    assert devices[0] == {
        "index": 0,
        "name": "Elgato 4K X",
        "width": 1920,
        "height": 1080,
        "fps": 60.0,
        "backend": int(cv2.CAP_MSMF),
        "dshow_index": None,
        "prefer_dshow": True,
        "ffmpeg_dshow_name": "Elgato 4K X",
    }
    assert not any(
        device["name"] == "Elgato 4K X" and device.get("dshow_index") == 0
        for device in devices
    )
