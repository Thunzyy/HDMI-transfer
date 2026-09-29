"""Reusable progress tracking with speed and ETA reporting.

Provides ``ProgressTracker`` for real-time transfer progress display during
both sequential and fountain receive operations.

Only stdlib imports (``time``).
"""

from __future__ import annotations

import time


class ProgressTracker:
    """Track transfer progress with speed (KB/s) and ETA estimation.

    Parameters
    ----------
    total_items:
        Total number of items (frames/droplets) expected.
    total_bytes:
        Total expected byte count for the transfer.
    warmup_s:
        Seconds before ETA estimation begins (default: 2.0).
    """

    def __init__(
        self,
        total_items: int,
        total_bytes: int,
        warmup_s: float = 2.0,
    ) -> None:
        self._total_items = total_items
        self._total_bytes = total_bytes
        self._warmup_ns = int(warmup_s * 1e9)
        self._start_ns = time.perf_counter_ns()
        self._received = 0
        self._bytes_received = 0

    # -- mutators ------------------------------------------------------------

    def update(self, items: int = 1, bytes_count: int = 0) -> None:
        """Increment received counters."""
        self._received += items
        self._bytes_received += bytes_count

    # -- properties ----------------------------------------------------------

    @property
    def received(self) -> int:
        """Number of items received so far."""
        return self._received

    @property
    def progress_pct(self) -> float:
        """Fraction of items received (0.0 -- 1.0)."""
        if self._total_items == 0:
            return 0.0
        return self._received / self._total_items

    @property
    def elapsed_ns(self) -> int:
        """Nanoseconds elapsed since tracker creation."""
        return time.perf_counter_ns() - self._start_ns

    @property
    def speed_bytes_per_sec(self) -> float:
        """Current throughput in bytes per second."""
        elapsed_s = self.elapsed_ns / 1e9
        if elapsed_s < 0.001:
            return 0.0
        return self._bytes_received / elapsed_s

    @property
    def eta_seconds(self) -> float:
        """Estimated seconds remaining (``inf`` during warmup or zero speed)."""
        if self.elapsed_ns < self._warmup_ns:
            return float("inf")
        speed = self.speed_bytes_per_sec
        if speed <= 0:
            return float("inf")
        remaining = self._total_bytes - self._bytes_received
        return remaining / speed

    # -- formatting ----------------------------------------------------------

    def format_line(self, extra: str = "") -> str:
        """Return a carriage-return-prefixed progress string.

        Format::

            \\rFrames: {received}/{total} ({pct:.1%}) | {speed:.1f} KB/s | ETA: {mm:ss}{extra}
        """
        speed_kb = self.speed_bytes_per_sec / 1024
        eta_str = self._format_eta(self.eta_seconds)
        return (
            f"\rFrames: {self._received}/{self._total_items} "
            f"({self.progress_pct:.1%}) | "
            f"{speed_kb:.1f} KB/s | ETA: {eta_str}"
            f"{extra}"
        )

    @staticmethod
    def _format_eta(seconds: float) -> str:
        """Convert *seconds* to ``m:ss`` or ``--:--`` for infinite values."""
        if seconds == float("inf") or seconds < 0:
            return "--:--"
        total_secs = int(seconds)
        mins = total_secs // 60
        secs = total_secs % 60
        return f"{mins}:{secs:02d}"
