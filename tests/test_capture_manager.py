"""Tests for centralized capture lifecycle management."""

from __future__ import annotations


class _FakeCapture:
    def __init__(self, *, opened: bool = True) -> None:
        self._opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self._opened

    def release(self) -> None:
        self.released = True
        self._opened = False


def test_capture_manager_reuses_matching_persistent_handle() -> None:
    from hdmi_exfil.adapters.capture.capture_manager import CaptureManager

    capture = _FakeCapture()
    manager = CaptureManager()

    manager.prime(device=1, backend=42, capture=capture)
    taken_capture, backend = manager.take(device=1)

    assert taken_capture is capture
    assert backend == 42


def test_capture_manager_release_clears_persistent_handle() -> None:
    from hdmi_exfil.adapters.capture.capture_manager import CaptureManager

    capture = _FakeCapture()
    manager = CaptureManager()
    manager.prime(device=2, backend=24, capture=capture)

    manager.release()

    taken_capture, backend = manager.take(device=2)
    assert taken_capture is None
    assert backend is None
    assert capture.released is True
