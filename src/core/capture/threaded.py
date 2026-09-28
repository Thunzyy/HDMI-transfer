"""Background-threaded video capture with ring buffer and FPS reporting.

Wraps any object with a ``.read()`` method (typically
:class:`~hdmi_transfer.receiver.capture.source.CaptureSource`) in a daemon thread that
continuously captures frames into a bounded :class:`collections.deque`.

Usage::

    with ThreadedCapture(CaptureSource(0)) as cap:
        while True:
            ret, frame = cap.read()
            if ret:
                process(frame)
"""

from __future__ import annotations

import threading
import time
from collections import deque


class FPSReporter:
    """Measures and reports actual FPS over a sliding window.

    Call :meth:`tick` once per frame.  It returns the measured FPS when the
    reporting interval elapses, otherwise ``None``.

    Parameters
    ----------
    report_interval_s:
        Seconds between FPS reports (default 1.0).
    """

    def __init__(self, report_interval_s: float = 1.0) -> None:
        self._interval_ns = int(report_interval_s * 1e9)
        self._window_frames = 0
        self._window_start_ns = time.perf_counter_ns()
        self._total_frames = 0

    def tick(self) -> float | None:
        """Record one frame.  Returns FPS when interval elapses, else None."""
        self._window_frames += 1
        self._total_frames += 1
        now = time.perf_counter_ns()
        elapsed = now - self._window_start_ns
        if elapsed >= self._interval_ns:
            fps = self._window_frames / (elapsed / 1e9)
            self._window_frames = 0
            self._window_start_ns = now
            return fps
        return None

    @property
    def total_frames(self) -> int:
        """Total number of frames recorded since creation."""
        return self._total_frames


class ThreadedCapture:
    """Background-threaded video capture with ring buffer.

    Wraps a capture source (or any object with a ``.read()`` method returning
    ``(bool, frame)``) in a daemon thread that continuously captures frames
    into a bounded :class:`collections.deque`.

    Parameters
    ----------
    source:
        Object with ``.read() -> (bool, ndarray)`` method (typically
        :class:`~hdmi_transfer.receiver.capture.source.CaptureSource`).
    buffer_size:
        Maximum frames in the ring buffer (default 16).
    """

    def __init__(
        self,
        source: object,
        buffer_size: int = 16,
        *,
        failed_read_sleep_s: float = 0.005,
    ) -> None:
        self._source = source
        self._buffer: deque = deque(maxlen=buffer_size)
        self._stopped = False
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._fps_reporter = FPSReporter()
        self._failed_read_sleep_s = failed_read_sleep_s

    def start(self) -> ThreadedCapture:
        """Start the background capture thread."""
        self._thread.start()
        return self

    def _capture_loop(self) -> None:
        """Continuously read frames from source into the ring buffer."""
        while not self._stopped:
            ret, frame = self._source.read()
            if ret:
                self._buffer.append(frame)
                self._fps_reporter.tick()
            else:
                time.sleep(self._failed_read_sleep_s)

    def read(self) -> tuple[bool, object]:
        """Non-blocking read of the next frame from the buffer.

        Returns
        -------
        tuple[bool, object]
            ``(True, frame)`` if a frame is available, ``(False, None)``
            when the buffer is empty.
        """
        try:
            return True, self._buffer.popleft()
        except IndexError:
            return False, None

    @property
    def actual_fps(self) -> float:
        """Measured frames per second from the capture thread.

        Returns the FPS over the current measurement window.  Returns 0.0
        when no frames have been captured or the window is stale (>2 s).
        """
        total = self._fps_reporter.total_frames
        if total == 0:
            return 0.0
        now = time.perf_counter_ns()
        start = self._fps_reporter._window_start_ns
        elapsed = (now - start) / 1e9
        if elapsed <= 0:
            return 0.0
        if elapsed < 2.0:
            return self._fps_reporter._window_frames / elapsed
        return 0.0

    @property
    def capture_fps_reporter(self) -> FPSReporter:
        """Direct access to the underlying :class:`FPSReporter`."""
        return self._fps_reporter

    @property
    def buffer_size(self) -> int:
        """Current number of frames in the ring buffer."""
        return len(self._buffer)

    def stop(self) -> None:
        """Signal the capture thread to stop and wait for it to finish."""
        self._stopped = True
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # -- Context manager -----------------------------------------------------

    def __enter__(self) -> ThreadedCapture:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_val: object,
        exc_tb: object,
    ) -> None:
        self.stop()
