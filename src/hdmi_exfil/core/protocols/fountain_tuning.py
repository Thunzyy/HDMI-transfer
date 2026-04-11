"""Shared tuning values for the fountain encoder/decoder pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FountainTuning:
    """Runtime tuning for RSD sampling, GE fallback, and budget gates."""

    degree_c: float
    degree_delta: float
    max_avg_overhead: float
    ge_max_total_chunks: int
    ge_max_unknowns: int
    ge_interval_unknown_threshold: int
    ge_min_interval_s: float
    ge_progress_min_gain_floor: int
    ge_progress_min_gain_divisor: int


DEFAULT_FOUNTAIN_TUNING = FountainTuning(
    degree_c=0.1,
    degree_delta=0.05,
    max_avg_overhead=1.10,
    ge_max_total_chunks=2048,
    ge_max_unknowns=1024,
    ge_interval_unknown_threshold=64,
    ge_min_interval_s=0.0,
    ge_progress_min_gain_floor=6,
    ge_progress_min_gain_divisor=24,
)


__all__ = ["DEFAULT_FOUNTAIN_TUNING", "FountainTuning"]
