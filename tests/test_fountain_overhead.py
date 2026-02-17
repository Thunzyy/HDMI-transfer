"""Overhead benchmarks for fountain codes with RSD + Gaussian elimination.

Measures decoding overhead (droplets_needed / K) across multiple K values
to verify the <10% overhead target for K>=100 and validate that RSD+GE
outperforms the old ad-hoc degree distribution.

All tests use seeded PRNG for deterministic, reproducible results.
Payload size is kept small (100 bytes) since overhead is independent of
payload size -- only the degree distribution matters.

Markers:
    @pytest.mark.slow -- Tests that take >10s (K>=500).  Skip with:
        pytest tests/test_fountain_overhead.py -v -k "not slow"
"""

from __future__ import annotations

import os
import statistics

import numpy as np
import pytest

from hdmi_exfil.prng import PRNG, choose_indices
from hdmi_exfil.protocols.degree import robust_soliton_cdf, sample_degree
from hdmi_exfil.protocols.fountain import FountainDecoder


# ---------------------------------------------------------------------------
# Small payload for fast benchmarks (overhead is payload-size-independent)
# ---------------------------------------------------------------------------
BENCH_PAYLOAD_SIZE: int = 100


# ---------------------------------------------------------------------------
# Helper: build a droplet from chunks using choose_indices
# ---------------------------------------------------------------------------

def _build_droplet(seed: int, K: int, chunks: list[bytes]) -> bytearray:
    """XOR chunks selected by choose_indices(seed, K)."""
    indices = set(choose_indices(seed, K))
    payload = bytearray(BENCH_PAYLOAD_SIZE)
    for idx in indices:
        for i in range(BENCH_PAYLOAD_SIZE):
            payload[i] ^= chunks[idx][i]
    return payload


# ---------------------------------------------------------------------------
# Core measurement function
# ---------------------------------------------------------------------------

def measure_overhead(
    K: int,
    runs: int = 20,
    max_multiplier: int = 5,
    seed_base: int = 0,
) -> tuple[float, float, float, list[float]]:
    """Measure average decoding overhead for given K across multiple runs.

    Each run generates K random chunks, encodes them as fountain droplets
    using sequential seeds, and counts how many droplets the decoder needs
    to recover all K chunks.

    Parameters
    ----------
    K : int
        Number of input chunks.
    runs : int
        Number of independent trials for statistical averaging.
    max_multiplier : int
        Maximum droplets = K * max_multiplier before declaring failure.
    seed_base : int
        Base seed offset for reproducibility across runs.

    Returns
    -------
    (avg_overhead, min_overhead, max_overhead, all_results)
        overhead = droplets_needed / K.  1.0 = perfect, 1.1 = 10% overhead.
    """
    results: list[float] = []

    for run in range(runs):
        # Deterministic chunks per run (seeded via run index)
        rng = np.random.RandomState(seed_base + run * 7919)
        chunks = [rng.bytes(BENCH_PAYLOAD_SIZE) for _ in range(K)]

        decoder = FountainDecoder(K, BENCH_PAYLOAD_SIZE)

        # Use deterministic, varied seeds per run
        seed = seed_base + run * 10000 + 1
        droplets = 0
        max_droplets = K * max_multiplier

        while not decoder.is_complete() and droplets < max_droplets:
            payload = _build_droplet(seed, K, chunks)
            decoder.add_droplet(seed, payload)
            droplets += 1
            seed += 1

        assert decoder.is_complete(), (
            f"Decoder did not complete: run={run}, K={K}, "
            f"droplets={droplets}/{max_droplets}, "
            f"recovered={len(decoder.chunks)}/{K}"
        )
        results.append(droplets / K)

    avg = statistics.mean(results)
    return (avg, min(results), max(results), results)


# ---------------------------------------------------------------------------
# Overhead benchmark tests by K value
# ---------------------------------------------------------------------------

class TestOverheadByK:
    """Parametrized overhead benchmarks for various K values."""

    def test_overhead_k10(self) -> None:
        """K=10: avg overhead < 1.50 (50% -- small K is inherently harder)."""
        avg, lo, hi, results = measure_overhead(K=10, runs=20, max_multiplier=10)
        assert avg < 1.50, (
            f"K=10 avg overhead {avg:.3f} exceeds 1.50 threshold "
            f"(min={lo:.3f}, max={hi:.3f})"
        )

    def test_overhead_k50(self) -> None:
        """K=50: avg overhead < 1.15 (15%)."""
        avg, lo, hi, results = measure_overhead(K=50, runs=20, max_multiplier=5)
        assert avg < 1.15, (
            f"K=50 avg overhead {avg:.3f} exceeds 1.15 threshold "
            f"(min={lo:.3f}, max={hi:.3f})"
        )

    def test_overhead_k100(self) -> None:
        """K=100: avg overhead < 1.10 (10% target)."""
        avg, lo, hi, results = measure_overhead(K=100, runs=20, max_multiplier=5)
        assert avg < 1.10, (
            f"K=100 avg overhead {avg:.3f} exceeds 1.10 threshold "
            f"(min={lo:.3f}, max={hi:.3f})"
        )

    @pytest.mark.slow
    def test_overhead_k500(self) -> None:
        """K=500: avg overhead < 1.10 (10% target)."""
        avg, lo, hi, results = measure_overhead(K=500, runs=20, max_multiplier=5)
        assert avg < 1.10, (
            f"K=500 avg overhead {avg:.3f} exceeds 1.10 threshold "
            f"(min={lo:.3f}, max={hi:.3f})"
        )

    @pytest.mark.slow
    def test_overhead_k1000(self) -> None:
        """K=1000: avg overhead < 1.10 (10% target)."""
        avg, lo, hi, results = measure_overhead(K=1000, runs=10, max_multiplier=5)
        assert avg < 1.10, (
            f"K=1000 avg overhead {avg:.3f} exceeds 1.10 threshold "
            f"(min={lo:.3f}, max={hi:.3f})"
        )


# ---------------------------------------------------------------------------
# RSD vs old ad-hoc distribution comparison
# ---------------------------------------------------------------------------

class TestRSDvsAdHoc:
    """Validate that RSD outperforms the old ad-hoc degree distribution."""

    def test_rsd_better_than_adhoc(self) -> None:
        """RSD+GE overhead is strictly lower than old ad-hoc ~30% overhead.

        The old ad-hoc distribution (10% deg-1, 50% deg-2, 40% random(1..20))
        had measured overhead of ~30%+ for typical K values (see RESEARCH.md).

        This test verifies RSD overhead at K=10, K=100, K=1000 is below the
        old ad-hoc baseline of 1.30.
        """
        adhoc_baseline = 1.30  # conservative: old distribution was ~30%+

        for K, runs in [(10, 20), (100, 10), (1000, 5)]:
            avg, _, _, _ = measure_overhead(
                K=K, runs=runs, max_multiplier=10, seed_base=42,
            )
            assert avg < adhoc_baseline, (
                f"RSD overhead {avg:.3f} at K={K} is NOT better than "
                f"ad-hoc baseline {adhoc_baseline}"
            )


# ---------------------------------------------------------------------------
# GE impact test: measure overhead with and without GE
# ---------------------------------------------------------------------------

class _NoGEDecoder(FountainDecoder):
    """FountainDecoder subclass with Gaussian elimination disabled.

    Overrides try_gaussian_elimination to be a no-op, so only BP peeling
    is used for decoding.  Used to measure GE's contribution to overhead
    reduction.
    """

    def try_gaussian_elimination(self) -> None:
        """No-op: skip GE entirely."""
        pass


def _measure_overhead_no_ge(
    K: int,
    runs: int = 20,
    max_multiplier: int = 10,
    seed_base: int = 0,
) -> tuple[float, float, float, list[float]]:
    """Same as measure_overhead but using BP-only decoder (no GE)."""
    results: list[float] = []

    for run in range(runs):
        rng = np.random.RandomState(seed_base + run * 7919)
        chunks = [rng.bytes(BENCH_PAYLOAD_SIZE) for _ in range(K)]

        decoder = _NoGEDecoder(K, BENCH_PAYLOAD_SIZE)

        seed = seed_base + run * 10000 + 1
        droplets = 0
        max_droplets = K * max_multiplier

        while not decoder.is_complete() and droplets < max_droplets:
            payload = _build_droplet(seed, K, chunks)
            decoder.add_droplet(seed, payload)
            droplets += 1
            seed += 1

        if not decoder.is_complete():
            # BP-only may not complete within budget for small K
            results.append(max_multiplier)
        else:
            results.append(droplets / K)

    avg = statistics.mean(results)
    return (avg, min(results), max(results), results)


class TestGEImpact:
    """Validate that GE reduces overhead, especially for small K."""

    def test_ge_reduces_overhead_k10(self) -> None:
        """GE+BP has lower or equal overhead than BP-only at K=10."""
        avg_ge, _, _, _ = measure_overhead(
            K=10, runs=20, max_multiplier=10, seed_base=100,
        )
        avg_no_ge, _, _, _ = _measure_overhead_no_ge(
            K=10, runs=20, max_multiplier=10, seed_base=100,
        )
        assert avg_ge <= avg_no_ge, (
            f"GE+BP ({avg_ge:.3f}) should be <= BP-only ({avg_no_ge:.3f}) "
            f"at K=10"
        )

    def test_ge_reduces_overhead_k20(self) -> None:
        """GE+BP has lower or equal overhead than BP-only at K=20."""
        avg_ge, _, _, _ = measure_overhead(
            K=20, runs=20, max_multiplier=10, seed_base=200,
        )
        avg_no_ge, _, _, _ = _measure_overhead_no_ge(
            K=20, runs=20, max_multiplier=10, seed_base=200,
        )
        assert avg_ge <= avg_no_ge, (
            f"GE+BP ({avg_ge:.3f}) should be <= BP-only ({avg_no_ge:.3f}) "
            f"at K=20"
        )


# ---------------------------------------------------------------------------
# Reproducibility test
# ---------------------------------------------------------------------------

class TestReproducibility:
    """Verify that overhead measurements are deterministic (seeded PRNG)."""

    def test_reproducible_results(self) -> None:
        """Two runs with same seed_base produce identical overhead values."""
        avg1, _, _, results1 = measure_overhead(
            K=50, runs=5, max_multiplier=5, seed_base=999,
        )
        avg2, _, _, results2 = measure_overhead(
            K=50, runs=5, max_multiplier=5, seed_base=999,
        )
        assert results1 == results2, (
            f"Results not reproducible: {results1} != {results2}"
        )
