"""SplitMix32 PRNG and fountain-code index selection.

Extracted from receiver_fountain.py -- bit-exact port of the JavaScript
SplitMix32 implementation used by sender.html.

The ``choose_indices`` helper uses the Robust Soliton Distribution (RSD)
from ``hdmi_exfil.core.protocols.degree`` for degree selection, replacing the
former ad-hoc distribution.
"""

from __future__ import annotations


class PRNG:
    """SplitMix32 pseudo-random number generator.

    Produces identical output to the JavaScript implementation in sender.html
    and the Python implementation formerly in receiver_fountain.py.
    """

    __slots__ = ("a",)

    def __init__(self, seed: int) -> None:
        self.a: int = int(seed) & 0xFFFFFFFF

    def next(self) -> int:
        self.a = (self.a | 0)
        self.a = (self.a + 0x9E3779B9) & 0xFFFFFFFF
        t = self.a ^ (self.a >> 16)
        t = (t * 0x21F0AAAD) & 0xFFFFFFFF
        t = t ^ (t >> 15)
        t = (t * 0x735A2D97) & 0xFFFFFFFF
        t = t ^ (t >> 15)
        return t & 0xFFFFFFFF

    def next_float(self) -> float:
        return self.next() / 4294967296.0


def choose_indices(seed: int, K: int) -> frozenset[int]:
    """Select fountain-code block indices for the given *seed* and *K* chunks.

    Uses the Robust Soliton Distribution (RSD) for degree selection,
    providing mathematically optimal overhead for LT codes.

    Degree is capped to ``min(degree, K)`` as a safety measure.

    Returns a *frozenset* (hashable, suitable for caching).
    """
    # Lazy import to avoid circular dependency:
    # prng -> protocols.degree -> (protocols.__init__ -> fountain -> prng)
    from hdmi_exfil.core.protocols.degree import robust_soliton_cdf, sample_degree

    prng = PRNG(seed)

    cdf = robust_soliton_cdf(K)
    degree = sample_degree(cdf, prng)

    # Safety cap: degree cannot exceed K
    degree = min(degree, K)

    indices: set[int] = set()
    while len(indices) < degree:
        idx = prng.next() % K
        indices.add(idx)

    return frozenset(indices)
