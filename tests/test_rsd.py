"""Unit tests for Robust Soliton Distribution (RSD) computation.

Tests the degree.py module: ideal_soliton, robust_soliton_cdf, sample_degree.
Verifies mathematical correctness, CDF monotonicity, determinism, caching,
and edge cases (K=1).
"""

from __future__ import annotations

import math

import pytest

from hdmi_transfer.protocols.degree import (
    DEFAULT_C,
    DEFAULT_DELTA,
    ideal_soliton,
    robust_soliton_cdf,
    sample_degree,
)
from hdmi_transfer.prng import PRNG


class TestIdealSoliton:
    """Tests for ideal_soliton(K) -> list[float]."""

    def test_ideal_soliton_k10_rho1(self):
        """rho(1) = 1/K for K=10."""
        rho = ideal_soliton(10)
        assert abs(rho[1] - 1.0 / 10) < 1e-12

    def test_ideal_soliton_k10_rho2(self):
        """rho(2) = 1/(2*1) = 0.5 for K=10."""
        rho = ideal_soliton(10)
        assert abs(rho[2] - 0.5) < 1e-12

    def test_ideal_soliton_k10_rho3(self):
        """rho(3) = 1/(3*2) = 0.1667 for K=10."""
        rho = ideal_soliton(10)
        assert abs(rho[3] - 1.0 / 6) < 1e-12

    def test_ideal_soliton_length(self):
        """ideal_soliton(K) returns list of length K+1 (0-indexed placeholder)."""
        rho = ideal_soliton(10)
        assert len(rho) == 11  # K+1

    def test_ideal_soliton_index_zero(self):
        """rho[0] = 0.0 (placeholder, degree 0 is impossible)."""
        rho = ideal_soliton(10)
        assert rho[0] == 0.0

    def test_ideal_soliton_sums_to_one(self):
        """Sum of rho(1..K) = 1.0 for the ideal soliton."""
        for K in [1, 5, 10, 100, 1000]:
            rho = ideal_soliton(K)
            total = sum(rho[1:])
            assert abs(total - 1.0) < 1e-10, f"K={K}: sum={total}"

    def test_ideal_soliton_k1(self):
        """K=1: rho(1) = 1.0 (trivially, degree is always 1)."""
        rho = ideal_soliton(1)
        assert len(rho) == 2
        assert rho[0] == 0.0
        assert abs(rho[1] - 1.0) < 1e-12


class TestRobustSolitonCDF:
    """Tests for robust_soliton_cdf(K, c, delta) -> tuple[float, ...]."""

    def test_cdf_length(self):
        """CDF has K+1 entries (0-indexed, CDF[0]=0.0)."""
        cdf = robust_soliton_cdf(100)
        assert len(cdf) == 101

    def test_cdf_starts_at_zero(self):
        """CDF[0] = 0.0."""
        cdf = robust_soliton_cdf(100)
        assert cdf[0] == 0.0

    def test_cdf_ends_at_one(self):
        """CDF[-1] = 1.0 (within floating point tolerance)."""
        for K in [1, 10, 100, 1000]:
            cdf = robust_soliton_cdf(K)
            assert abs(cdf[-1] - 1.0) < 1e-10, f"K={K}: CDF[-1]={cdf[-1]}"

    def test_cdf_monotonically_increasing(self):
        """CDF is monotonically non-decreasing."""
        for K in [10, 100, 500]:
            cdf = robust_soliton_cdf(K)
            for i in range(1, len(cdf)):
                assert cdf[i] >= cdf[i - 1] - 1e-15, (
                    f"K={K}: CDF[{i}]={cdf[i]} < CDF[{i-1}]={cdf[i-1]}"
                )

    def test_cdf_k1_trivial(self):
        """K=1: CDF = (0.0, 1.0) -- always degree 1."""
        cdf = robust_soliton_cdf(1)
        assert cdf == (0.0, 1.0)

    def test_cdf_returns_tuple(self):
        """CDF is a tuple (hashable, cacheable)."""
        cdf = robust_soliton_cdf(100)
        assert isinstance(cdf, tuple)

    def test_cdf_is_cached(self):
        """Same (K, c, delta) returns the same object (lru_cache)."""
        cdf1 = robust_soliton_cdf(100, 0.1, 0.05)
        cdf2 = robust_soliton_cdf(100, 0.1, 0.05)
        assert cdf1 is cdf2  # identity check, not equality

    def test_cdf_different_params_differ(self):
        """Different (c, delta) produce different CDFs."""
        cdf_a = robust_soliton_cdf(100, 0.1, 0.05)
        cdf_b = robust_soliton_cdf(100, 0.2, 0.05)
        assert cdf_a != cdf_b

    def test_cdf_k10000(self):
        """CDF computes without error for large K=10000."""
        cdf = robust_soliton_cdf(10000)
        assert len(cdf) == 10001
        assert abs(cdf[-1] - 1.0) < 1e-10


class TestSampleDegree:
    """Tests for sample_degree(cdf, prng) -> int."""

    def test_sample_degree_returns_int(self):
        """sample_degree returns an integer."""
        cdf = robust_soliton_cdf(100)
        prng = PRNG(42)
        degree = sample_degree(cdf, prng)
        assert isinstance(degree, int)

    def test_sample_degree_in_range(self):
        """sample_degree returns a value in [1, K]."""
        K = 100
        cdf = robust_soliton_cdf(K)
        for seed in range(1, 101):
            prng = PRNG(seed)
            degree = sample_degree(cdf, prng)
            assert 1 <= degree <= K, f"seed={seed}: degree={degree}"

    def test_sample_degree_deterministic(self):
        """Same seed always produces the same degree."""
        cdf = robust_soliton_cdf(100)
        results = []
        for _ in range(10):
            prng = PRNG(42)
            results.append(sample_degree(cdf, prng))
        assert len(set(results)) == 1, f"Non-deterministic: {results}"

    def test_sample_degree_k1_always_one(self):
        """K=1: degree is always 1 regardless of seed."""
        cdf = robust_soliton_cdf(1)
        for seed in range(1, 50):
            prng = PRNG(seed)
            degree = sample_degree(cdf, prng)
            assert degree == 1, f"seed={seed}: degree={degree}"

    def test_sample_degree_distribution_shape(self):
        """RSD should produce mostly low degrees with a spike at degree 1 and 2.

        For K=100, over 10000 samples, degree 1 and 2 should dominate.
        """
        K = 100
        cdf = robust_soliton_cdf(K)
        counts = [0] * (K + 1)
        n_samples = 10000

        for seed in range(1, n_samples + 1):
            prng = PRNG(seed)
            d = sample_degree(cdf, prng)
            counts[d] += 1

        # Degree 1 and 2 should together account for a significant fraction
        low_degree_frac = (counts[1] + counts[2]) / n_samples
        assert low_degree_frac > 0.3, (
            f"Low degrees (1+2) = {low_degree_frac:.2%}, expected > 30%"
        )


class TestDefaultConstants:
    """Tests for default parameter constants."""

    def test_default_c(self):
        """DEFAULT_C = 0.1."""
        assert DEFAULT_C == 0.1

    def test_default_delta(self):
        """DEFAULT_DELTA = 0.05."""
        assert DEFAULT_DELTA == 0.05
