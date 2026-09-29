"""Robust Soliton Distribution (RSD) for LT fountain codes.

Provides the mathematically optimal degree distribution for LT codes,
replacing the ad-hoc distribution (10% degree-1, 50% degree-2, 40% random)
that was previously duplicated across multiple files.

Functions:
    ideal_soliton(K)           -- Ideal Soliton Distribution (ISD) PMF
    robust_soliton_cdf(K,c,d)  -- Robust Soliton Distribution CDF (cached)
    sample_degree(cdf, prng)   -- Sample a degree from the CDF using PRNG

Constants:
    DEFAULT_C     -- ripple tuning constant from fountain_tuning
    DEFAULT_DELTA -- failure probability bound from fountain_tuning
"""

from __future__ import annotations

import bisect
import math
from functools import lru_cache

from hdmi_transfer.core.protocols.fountain_tuning import DEFAULT_FOUNTAIN_TUNING

# ---------------------------------------------------------------------------
# Default parameters
# ---------------------------------------------------------------------------
#
# RSD defaults are owned by the fountain tuning module.
# Performance claims belong in tests, not comments.
# ---------------------------------------------------------------------------

DEFAULT_C: float = DEFAULT_FOUNTAIN_TUNING.degree_c
"""Ripple tuning constant for the robust soliton distribution."""

DEFAULT_DELTA: float = DEFAULT_FOUNTAIN_TUNING.degree_delta
"""Failure probability bound for the robust soliton distribution."""


# ---------------------------------------------------------------------------
# Ideal Soliton Distribution
# ---------------------------------------------------------------------------

def ideal_soliton(K: int) -> list[float]:
    """Compute the Ideal Soliton Distribution PMF for *K* input symbols.

    Returns a list of length K+1 (1-indexed).  ``rho[0] = 0.0`` is a
    placeholder; valid degrees are ``1..K``.

    Formula:
        rho(1) = 1/K
        rho(d) = 1 / (d * (d - 1))   for d = 2..K
    """
    rho = [0.0] * (K + 1)
    if K == 1:
        rho[1] = 1.0
        return rho

    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))
    return rho


# ---------------------------------------------------------------------------
# Robust Soliton Distribution (CDF)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def robust_soliton_cdf(
    K: int,
    c: float = DEFAULT_C,
    delta: float = DEFAULT_DELTA,
) -> tuple[float, ...]:
    """Compute the cumulative distribution function for the RSD.

    The CDF is a tuple of length K+1.  ``cdf[0] = 0.0``; ``cdf[K] = 1.0``.
    Use with :func:`sample_degree` to draw degrees deterministically.

    Parameters
    ----------
    K : int
        Number of input symbols (chunks).
    c : float
        Ripple tuning constant (default 0.1).
    delta : float
        Failure probability bound (default 0.05).

    Returns
    -------
    tuple[float, ...]
        Cumulative distribution of the robust soliton, length K+1.
    """
    # Trivial case: K=1 always has degree 1
    if K == 1:
        return (0.0, 1.0)

    # Ideal soliton
    rho = ideal_soliton(K)

    # Expected ripple size: S = c * ln(K/delta) * sqrt(K)
    S = c * math.log(K / delta) * math.sqrt(K)

    # Pivot = floor(K / S)
    pivot = max(1, int(math.floor(K / S)))

    # Tau distribution
    tau = [0.0] * (K + 1)
    for d in range(1, min(pivot, K + 1)):
        tau[d] = S / (K * d)
    if pivot <= K:
        tau[pivot] += (S / K) * math.log(S / delta)

    # Combined unnormalized PMF: mu_unnorm(d) = rho(d) + tau(d)
    mu_unnorm = [rho[d] + tau[d] for d in range(K + 1)]
    # mu_unnorm[0] = 0.0 (no degree-0)

    # Normalize
    Z = sum(mu_unnorm[1:])
    mu = [0.0] + [mu_unnorm[d] / Z for d in range(1, K + 1)]

    # Build CDF via cumulative sum
    cdf = [0.0] * (K + 1)
    for d in range(1, K + 1):
        cdf[d] = cdf[d - 1] + mu[d]

    # Force last entry to exactly 1.0 to avoid floating-point drift
    cdf[K] = 1.0

    return tuple(cdf)


# ---------------------------------------------------------------------------
# Degree sampling
# ---------------------------------------------------------------------------

def sample_degree(cdf: tuple[float, ...], prng: object) -> int:
    """Sample a degree from the RSD using the given PRNG.

    Uses binary search on the CDF for O(log K) lookup.  The *prng* must
    expose a ``next_float() -> float`` method (e.g. ``hdmi_transfer.core.prng.PRNG``).

    Parameters
    ----------
    cdf : tuple[float, ...]
        Robust soliton CDF from :func:`robust_soliton_cdf`.
    prng : object
        PRNG instance with a ``next_float()`` method.

    Returns
    -------
    int
        Sampled degree in ``[1, K]`` where ``K = len(cdf) - 1``.
    """
    r = prng.next_float()  # type: ignore[attr-defined]

    # bisect_right finds insertion point; degree = position (1-indexed)
    # CDF: [0.0, cdf[1], cdf[2], ..., 1.0]
    # For r in [0, cdf[1]) -> degree 1, [cdf[1], cdf[2]) -> degree 2, etc.
    K = len(cdf) - 1
    degree = bisect.bisect_left(cdf, r, lo=1, hi=K + 1)

    # Clamp to valid range [1, K]
    return max(1, min(degree, K))
