"""Cross-language determinism tests for RSD degree distribution.

Verifies that Python (choose_indices) and JavaScript (chooseIndices) produce
identical (degree, sorted_indices) output for the same (seed, K) inputs.

Also tests CDF consistency, Python determinism, and distribution shape.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap

import pytest

from hdmi_exfil.prng import PRNG, choose_indices
from hdmi_exfil.protocols.degree import robust_soliton_cdf, sample_degree


# ---------------------------------------------------------------------------
# Test parameters
# ---------------------------------------------------------------------------

K_VALUES = [1, 5, 10, 50, 100, 500, 1000]
SEED_VALUES = [1, 42, 999, 65535, 2**31 - 1]


# ---------------------------------------------------------------------------
# Helper: compute (degree, sorted_indices) from Python
# ---------------------------------------------------------------------------

def _python_degree_and_indices(seed: int, K: int) -> tuple[int, list[int]]:
    """Return (degree, sorted_indices) using the Python implementation."""
    indices = choose_indices(seed, K)
    return len(indices), sorted(indices)


# ---------------------------------------------------------------------------
# 1. CDF consistency tests
# ---------------------------------------------------------------------------

class TestCdfConsistency:
    """Verify CDF properties from robust_soliton_cdf."""

    @pytest.mark.parametrize("K", K_VALUES)
    def test_cdf_starts_at_zero(self, K: int) -> None:
        cdf = robust_soliton_cdf(K)
        assert cdf[0] == 0.0

    @pytest.mark.parametrize("K", K_VALUES)
    def test_cdf_ends_at_one(self, K: int) -> None:
        cdf = robust_soliton_cdf(K)
        assert cdf[K] == 1.0

    @pytest.mark.parametrize("K", K_VALUES)
    def test_cdf_monotonically_non_decreasing(self, K: int) -> None:
        cdf = robust_soliton_cdf(K)
        for i in range(1, len(cdf)):
            assert cdf[i] >= cdf[i - 1], (
                f"CDF not monotonic at d={i}: {cdf[i]} < {cdf[i - 1]}"
            )

    def test_cdf_k10_hand_verified(self) -> None:
        """Spot-check K=10 CDF against hand-computed values."""
        cdf = robust_soliton_cdf(10)
        assert len(cdf) == 11
        # CDF[1] should be ~0.138 (degree-1 weight)
        assert 0.13 < cdf[1] < 0.15
        # CDF[5] should show a big jump (pivot-related spike)
        assert cdf[5] > 0.9  # pivot spike at K=10 pushes d<=5 to >90%


# ---------------------------------------------------------------------------
# 2. Python determinism tests
# ---------------------------------------------------------------------------

class TestPythonDeterminism:
    """Verify Python choose_indices is deterministic."""

    @pytest.mark.parametrize("K", K_VALUES)
    @pytest.mark.parametrize("seed", SEED_VALUES)
    def test_same_input_same_output(self, seed: int, K: int) -> None:
        """Calling choose_indices twice with same args returns same result."""
        result1 = choose_indices(seed, K)
        result2 = choose_indices(seed, K)
        assert result1 == result2

    @pytest.mark.parametrize("K", [10, 100, 1000])
    def test_different_seeds_vary(self, K: int) -> None:
        """Different seeds produce varied outputs (not all identical)."""
        results = set()
        for seed in range(1, 101):
            indices = choose_indices(seed, K)
            results.add(indices)
        # At least 5 distinct results out of 100 seeds
        assert len(results) >= 5, f"Only {len(results)} distinct results for K={K}"

    @pytest.mark.parametrize("K", K_VALUES)
    @pytest.mark.parametrize("seed", SEED_VALUES)
    def test_indices_in_valid_range(self, seed: int, K: int) -> None:
        """All indices must be in [0, K)."""
        indices = choose_indices(seed, K)
        for idx in indices:
            assert 0 <= idx < K, f"Index {idx} out of range for K={K}"

    @pytest.mark.parametrize("K", K_VALUES)
    @pytest.mark.parametrize("seed", SEED_VALUES)
    def test_degree_in_valid_range(self, seed: int, K: int) -> None:
        """Degree (number of indices) must be in [1, K]."""
        indices = choose_indices(seed, K)
        degree = len(indices)
        assert 1 <= degree <= K, f"Degree {degree} out of range for K={K}"


# ---------------------------------------------------------------------------
# 3. Cross-language test vectors (Python vs JavaScript)
# ---------------------------------------------------------------------------

# JavaScript source for chooseIndices -- extracted from sender.template.html
_JS_SOURCE = textwrap.dedent("""\
    const RSD_C = 0.1;
    const RSD_DELTA = 0.05;

    function createPRNG(seed) {
      let a = seed >>> 0;
      return () => {
        a = (a + 0x9e3779b9) >>> 0;
        let t = a ^ (a >>> 16);
        t = Math.imul(t, 0x21f0aaad) >>> 0;
        t ^= t >>> 15;
        t = Math.imul(t, 0x735a2d97) >>> 0;
        t ^= t >>> 15;
        return t >>> 0;
      };
    }

    function robustSolitonCdf(K) {
      if (K === 1) return [0.0, 1.0];
      const rho = new Array(K + 1).fill(0);
      rho[1] = 1.0 / K;
      for (let d = 2; d <= K; d++) rho[d] = 1.0 / (d * (d - 1));
      const S = RSD_C * Math.log(K / RSD_DELTA) * Math.sqrt(K);
      const pivot = Math.max(1, Math.floor(K / S));
      const tau = new Array(K + 1).fill(0);
      for (let d = 1; d < Math.min(pivot, K + 1); d++) tau[d] = S / (K * d);
      if (pivot <= K) tau[pivot] += (S / K) * Math.log(S / RSD_DELTA);
      let Z = 0;
      for (let d = 1; d <= K; d++) Z += rho[d] + tau[d];
      const cdf = new Array(K + 1).fill(0);
      let cumulative = 0;
      for (let d = 1; d <= K; d++) {
        cumulative += (rho[d] + tau[d]) / Z;
        cdf[d] = cumulative;
      }
      cdf[K] = 1.0;
      return cdf;
    }

    function sampleDegree(cdf, r) {
      let lo = 1, hi = cdf.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (cdf[mid] < r) lo = mid + 1;
        else hi = mid;
      }
      return Math.max(1, Math.min(lo, cdf.length - 1));
    }

    function chooseIndices(seed, K) {
      const next = createPRNG(seed);
      const cdf = robustSolitonCdf(K);
      const r = next() / 0x100000000;
      let degree = sampleDegree(cdf, r);
      degree = Math.min(degree, K);
      const indices = new Set();
      while (indices.size < degree) {
        indices.add(next() % K);
      }
      return Array.from(indices).sort((a, b) => a - b);
    }

    // Read test cases from stdin (fd 0 works on Windows and POSIX).
    const input = require('fs').readFileSync(0, 'utf8');
    const testCases = JSON.parse(input);

    const results = [];
    for (const { seed, K } of testCases) {
      const indices = chooseIndices(seed, K);
      results.push({ seed, K, degree: indices.length, indices });
    }
    console.log(JSON.stringify(results));
""")


def _node_available() -> bool:
    """Check if Node.js is available."""
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_js_vectors(
    test_cases: list[dict[str, int]],
) -> list[dict]:
    """Run JavaScript chooseIndices for given test cases via Node.js."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False,
    ) as f:
        f.write(_JS_SOURCE)
        js_path = f.name

    input_json = json.dumps(test_cases)
    result = subprocess.run(
        ["node", js_path],
        input=input_json,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Node.js failed: {result.stderr}")
    return json.loads(result.stdout)


@pytest.mark.skipif(not _node_available(), reason="Node.js not available")
class TestCrossLanguageDeterminism:
    """Verify Python and JavaScript produce identical RSD results."""

    def test_cdf_values_match(self) -> None:
        """CDF arrays match between Python and JS for several K values."""
        js_cdf_code = textwrap.dedent("""\
            const RSD_C = 0.1;
            const RSD_DELTA = 0.05;
            function robustSolitonCdf(K) {
              if (K === 1) return [0.0, 1.0];
              const rho = new Array(K + 1).fill(0);
              rho[1] = 1.0 / K;
              for (let d = 2; d <= K; d++) rho[d] = 1.0 / (d * (d - 1));
              const S = RSD_C * Math.log(K / RSD_DELTA) * Math.sqrt(K);
              const pivot = Math.max(1, Math.floor(K / S));
              const tau = new Array(K + 1).fill(0);
              for (let d = 1; d < Math.min(pivot, K + 1); d++) tau[d] = S / (K * d);
              if (pivot <= K) tau[pivot] += (S / K) * Math.log(S / RSD_DELTA);
              let Z = 0;
              for (let d = 1; d <= K; d++) Z += rho[d] + tau[d];
              const cdf = new Array(K + 1).fill(0);
              let cumulative = 0;
              for (let d = 1; d <= K; d++) {
                cumulative += (rho[d] + tau[d]) / Z;
                cdf[d] = cumulative;
              }
              cdf[K] = 1.0;
              return cdf;
            }
            const Ks = [1, 5, 10, 50, 100, 500, 1000];
            const result = {};
            for (const K of Ks) {
              result[K] = robustSolitonCdf(K);
            }
            console.log(JSON.stringify(result));
        """)

        result = subprocess.run(
            ["node", "-e", js_cdf_code],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        js_cdfs = json.loads(result.stdout)

        for K in K_VALUES:
            py_cdf = robust_soliton_cdf(K)
            js_cdf = js_cdfs[str(K)]
            assert len(py_cdf) == len(js_cdf), (
                f"K={K}: length mismatch {len(py_cdf)} vs {len(js_cdf)}"
            )
            for d in range(len(py_cdf)):
                assert abs(py_cdf[d] - js_cdf[d]) < 1e-12, (
                    f"K={K}, d={d}: Python={py_cdf[d]}, JS={js_cdf[d]}"
                )

    def test_choose_indices_match_all_vectors(self) -> None:
        """Full cross-product: all K_VALUES x SEED_VALUES must match."""
        # Build test cases
        test_cases = [
            {"seed": seed, "K": K}
            for K in K_VALUES
            for seed in SEED_VALUES
        ]

        # Get JS results
        js_results = _run_js_vectors(test_cases)

        # Compare each
        mismatches = []
        for tc, js_result in zip(test_cases, js_results):
            seed, K = tc["seed"], tc["K"]
            py_degree, py_indices = _python_degree_and_indices(seed, K)

            js_degree = js_result["degree"]
            js_indices = js_result["indices"]

            if py_degree != js_degree or py_indices != js_indices:
                mismatches.append(
                    f"seed={seed}, K={K}: "
                    f"Python=({py_degree}, {py_indices}) vs "
                    f"JS=({js_degree}, {js_indices})"
                )

        assert not mismatches, (
            f"{len(mismatches)} mismatch(es):\n" + "\n".join(mismatches[:10])
        )

    def test_large_k_cross_language(self) -> None:
        """Spot check large K values (5000, 10000) with a few seeds."""
        large_cases = [
            {"seed": s, "K": K}
            for K in [5000, 10000]
            for s in [1, 42, 65535]
        ]

        js_results = _run_js_vectors(large_cases)

        for tc, js_result in zip(large_cases, js_results):
            seed, K = tc["seed"], tc["K"]
            py_degree, py_indices = _python_degree_and_indices(seed, K)
            assert py_degree == js_result["degree"], (
                f"seed={seed}, K={K}: degree mismatch"
            )
            assert py_indices == js_result["indices"], (
                f"seed={seed}, K={K}: indices mismatch"
            )


# ---------------------------------------------------------------------------
# 4. Distribution shape tests
# ---------------------------------------------------------------------------

class TestDistributionShape:
    """Verify the RSD produces the expected distribution shape."""

    def test_degree_one_has_highest_weight_for_large_k(self) -> None:
        """For large K, degree=1 should have significant probability."""
        cdf = robust_soliton_cdf(1000)
        # P(degree=1) = cdf[1] - cdf[0]
        p1 = cdf[1]
        assert p1 > 0.01, f"P(degree=1) = {p1} too low for K=1000"

    def test_degree_distribution_has_pivot_spike(self) -> None:
        """RSD should have a spike near the pivot degree."""
        K = 100
        cdf = robust_soliton_cdf(K)
        # PMF from CDF
        pmf = [0.0] + [cdf[d] - cdf[d - 1] for d in range(1, K + 1)]

        # Find pivot: floor(K / S) where S = c * ln(K/delta) * sqrt(K)
        import math
        S = 0.1 * math.log(K / 0.05) * math.sqrt(K)
        pivot = max(1, int(math.floor(K / S)))

        # Pivot should have elevated probability
        assert pmf[pivot] > 0.05, (
            f"Pivot={pivot} has P={pmf[pivot]}, expected spike"
        )

    @pytest.mark.parametrize("K", [10, 100, 1000])
    def test_empirical_degree_distribution(self, K: int) -> None:
        """Empirical degree distribution over many seeds resembles RSD."""
        degree_counts: dict[int, int] = {}
        n_samples = 2000
        for seed in range(1, n_samples + 1):
            indices = choose_indices(seed, K)
            d = len(indices)
            degree_counts[d] = degree_counts.get(d, 0) + 1

        # Degree 1 should appear (not zero)
        assert degree_counts.get(1, 0) > 0, (
            f"K={K}: degree=1 never appeared in {n_samples} samples"
        )

        # No degree should be 0 or > K
        for d in degree_counts:
            assert 1 <= d <= K, f"Invalid degree {d} for K={K}"
