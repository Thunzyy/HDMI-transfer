"""Unit tests for ThreadedCapture and FPSReporter."""

from __future__ import annotations

import time

import numpy as np
import pytest

from hdmi_transfer.capture.threaded import FPSReporter, ThreadedCapture


# ---------------------------------------------------------------------------
# Mock source for testing
# ---------------------------------------------------------------------------


class MockSource:
    """Simulates a video capture device that produces numbered frames."""

    def __init__(self, frame_count: int = 100, delay_s: float = 0.001) -> None:
        self._count = 0
        self._max = frame_count
        self._delay = delay_s

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._count >= self._max:
            time.sleep(0.1)
            return False, None
        self._count += 1
        time.sleep(self._delay)
        frame = np.full((1080, 1920, 3), self._count, dtype=np.uint8)
        return True, frame


class AlwaysFailSource:
    """Simulates a source that never produces frames."""

    def __init__(self) -> None:
        self.read_count = 0

    def read(self) -> tuple[bool, None]:
        self.read_count += 1
        return False, None


# ---------------------------------------------------------------------------
# FPSReporter tests
# ---------------------------------------------------------------------------


class TestFPSReporter:
    def test_basic_fps_report(self) -> None:
        """FPSReporter eventually returns a float > 0 after enough ticks."""
        reporter = FPSReporter(report_interval_s=0.01)
        fps_value = None
        for _ in range(500):
            result = reporter.tick()
            if result is not None:
                fps_value = result
                break
            time.sleep(0.0001)

        assert fps_value is not None, "FPSReporter never reported FPS"
        assert isinstance(fps_value, float)
        assert fps_value > 0

    def test_total_frames(self) -> None:
        """total_frames increments with each tick() call."""
        reporter = FPSReporter(report_interval_s=10.0)  # long interval
        n = 42
        for _ in range(n):
            reporter.tick()

        assert reporter.total_frames == n

    def test_returns_none_before_interval(self) -> None:
        """tick() returns None before the reporting interval elapses."""
        reporter = FPSReporter(report_interval_s=100.0)  # very long
        assert reporter.tick() is None
        assert reporter.tick() is None


# ---------------------------------------------------------------------------
# ThreadedCapture tests
# ---------------------------------------------------------------------------


class TestThreadedCapture:
    def test_produces_frames(self) -> None:
        """ThreadedCapture reads frames from the source in background."""
        source = MockSource(frame_count=50, delay_s=0.001)
        cap = ThreadedCapture(source, buffer_size=16)
        cap.start()
        try:
            # Give the background thread time to capture some frames
            time.sleep(0.15)

            got_frames = 0
            for _ in range(50):
                ret, frame = cap.read()
                if ret:
                    assert frame is not None
                    assert frame.shape == (1080, 1920, 3)
                    got_frames += 1

            assert got_frames > 0, "ThreadedCapture produced no frames"
        finally:
            cap.stop()

    def test_empty_buffer_returns_false(self) -> None:
        """read() returns (False, None) when buffer is empty (not started)."""
        source = MockSource(frame_count=10)
        cap = ThreadedCapture(source, buffer_size=4)
        # Do NOT start -- buffer should be empty
        ret, frame = cap.read()
        assert ret is False
        assert frame is None

    def test_context_manager(self) -> None:
        """Context manager starts capture and stops on exit."""
        source = MockSource(frame_count=50, delay_s=0.001)
        with ThreadedCapture(source, buffer_size=16) as cap:
            time.sleep(0.1)
            ret, frame = cap.read()
            # Should have at least one frame after 100ms
            assert ret is True
            assert frame is not None

        # After exit, thread should be stopped
        assert cap._stopped is True

    def test_buffer_bounded(self) -> None:
        """Ring buffer never exceeds the configured max size."""
        source = MockSource(frame_count=200, delay_s=0.0001)
        max_buf = 4
        cap = ThreadedCapture(source, buffer_size=max_buf)
        cap.start()
        try:
            # Let the fast source fill the buffer well beyond max_buf
            time.sleep(0.2)
            assert cap.buffer_size <= max_buf
        finally:
            cap.stop()

    def test_actual_fps_zero_before_capture(self) -> None:
        """actual_fps returns 0.0 before any frames are captured."""
        source = MockSource(frame_count=10)
        cap = ThreadedCapture(source, buffer_size=4)
        assert cap.actual_fps == 0.0

    def test_capture_fps_reporter_accessible(self) -> None:
        """capture_fps_reporter property returns the internal FPSReporter."""
        source = MockSource(frame_count=10)
        cap = ThreadedCapture(source, buffer_size=4)
        reporter = cap.capture_fps_reporter
        assert isinstance(reporter, FPSReporter)

    def test_stop_is_idempotent(self) -> None:
        """Calling stop() multiple times does not raise."""
        source = MockSource(frame_count=10, delay_s=0.01)
        cap = ThreadedCapture(source, buffer_size=4)
        cap.start()
        time.sleep(0.05)
        cap.stop()
        cap.stop()  # Should not raise

    def test_failed_reads_back_off_instead_of_spinning(self) -> None:
        """Repeated failed reads should sleep briefly instead of tight-looping."""
        source = AlwaysFailSource()
        cap = ThreadedCapture(source, buffer_size=4)
        cap.start()
        try:
            time.sleep(0.05)
        finally:
            cap.stop()

        assert source.read_count < 200
