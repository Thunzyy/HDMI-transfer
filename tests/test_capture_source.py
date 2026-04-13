from __future__ import annotations

import cv2
import numpy as np


class _FakeVideoCapture:
    def __init__(self, frames: list[np.ndarray | None], *, opened: bool = True) -> None:
        self._frames = list(frames)
        self._opened = opened
        self._width = 640
        self._height = 480
        self._fps = 30.0

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
        frame = self._frames.pop(0)
        if frame is None:
            return False, None
        return True, frame

    def release(self) -> None:
        self._opened = False


def test_capture_source_accepts_black_dshow_frames_when_reads_succeed(monkeypatch):
    from hdmi_exfil.receiver.capture.source import CaptureSource

    black = np.zeros((1080, 1920, 3), dtype=np.uint8)

    monkeypatch.setattr(
        cv2,
        "VideoCapture",
        lambda source, backend: _FakeVideoCapture([black.copy() for _ in range(8)]),
    )

    cap = CaptureSource(3, width=1920, height=1080, fps=60, backend=cv2.CAP_DSHOW)

    assert cap.actual_width == 1920
    assert cap.actual_height == 1080
    cap.release()


def test_capture_source_rejects_dshow_when_no_frames_are_read(monkeypatch):
    from hdmi_exfil.receiver.capture.source import CaptureSource

    monkeypatch.setattr(
        cv2,
        "VideoCapture",
        lambda source, backend: _FakeVideoCapture([None for _ in range(8)]),
    )

    try:
        CaptureSource(3, width=1920, height=1080, fps=60, backend=cv2.CAP_DSHOW)
    except RuntimeError as exc:
        assert "Could not open video source 3" in str(exc)
    else:
        raise AssertionError("CaptureSource should reject DSHOW sources with no readable frames")
