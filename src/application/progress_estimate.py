"""Steady transfer progress and an ETA that follows the current rate.

Fountain decoding is not linear: belief propagation resolves almost nothing
until about K droplets have arrived, then most chunks cascade at once (around
90 % of the needed droplets only ~5 % of chunks are decoded). Progress is
therefore measured on received information (unique droplets against the
expected need), and decoded chunks only take over when they are ahead.
"""

from __future__ import annotations

from collections import deque
import math

from hdmi_transfer.core.protocols.fountain_tuning import DEFAULT_FOUNTAIN_TUNING

# Measured unique droplets per chunk before decoding completes. Gaussian
# elimination finishes small residual systems close to K; above its unknowns
# cap only peeling runs and about 20 % more droplets are needed.
_OVERHEAD_WITH_GE = 1.05
_OVERHEAD_PEELING_ONLY = 1.20
# Once the estimate is exceeded, keep the bar just short of the end.
_LATE_TAIL = 0.98


def fountain_droplets_needed(total_chunks: int, *, unique: int) -> int:
    """Estimated unique droplets needed to decode ``total_chunks`` chunks."""
    overhead = (
        _OVERHEAD_WITH_GE
        if total_chunks <= DEFAULT_FOUNTAIN_TUNING.ge_max_unknowns
        else _OVERHEAD_PEELING_ONLY
    )
    base = math.ceil(total_chunks * overhead)
    if unique >= base * _LATE_TAIL:
        return max(base, math.ceil(unique / _LATE_TAIL))
    return base


class ProgressEstimator:
    """Monotonic percent plus an ETA from the rate over a sliding window."""

    def __init__(self, *, window_s: float = 15.0, min_span_s: float = 2.0) -> None:
        self._window_s = window_s
        self._min_span_s = min_span_s
        self.reset()

    def reset(self) -> None:
        self._samples: deque[tuple[float, float]] = deque()
        self._best = 0.0

    def update(
        self,
        *,
        now: float,
        done: float,
        total: float,
        decoded_fraction: float = 0.0,
    ) -> tuple[float, float]:
        """Return ``(percent, eta_seconds)``; ETA is -1 while unknown."""
        fraction = done / total if total > 0 else 0.0
        fraction = min(max(fraction, decoded_fraction), 0.999)
        self._best = max(self._best, fraction)

        self._samples.append((now, done))
        while len(self._samples) > 1 and now - self._samples[1][0] >= self._window_s:
            self._samples.popleft()
        start_at, start_done = self._samples[0]
        span = now - start_at
        gained = done - start_done
        remaining = total - done
        eta = -1.0
        if span >= self._min_span_s and gained > 0 and remaining > 0:
            eta = round(remaining / (gained / span), 1)
        return round(self._best * 100, 1), eta


__all__ = ["ProgressEstimator", "fountain_droplets_needed"]
