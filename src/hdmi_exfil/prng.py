"""SplitMix32 PRNG and fountain-code index selection.

Extracted from receiver_fountain.py -- bit-exact port of the JavaScript
SplitMix32 implementation used by sender.html.

The ``choose_indices`` helper replicates the degree-distribution and index
selection logic shared by both the JS sender and the Python fountain receiver.
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

    Degree distribution (must match JS exactly):
      - r < 0.1  -> degree = 1
      - r < 0.6  -> degree = 2
      - else     -> degree = floor(next_float * min(K, 20)) + 1

    Degree is capped to ``min(degree, K)`` to prevent an infinite loop when
    ``degree > K`` (bug-fix from Phase 2, decision 02-02).

    Returns a *frozenset* (hashable, suitable for caching).
    """
    prng = PRNG(seed)

    r = prng.next_float()
    if r < 0.1:
        degree = 1
    elif r < 0.6:
        degree = 2
    else:
        degree = int(prng.next_float() * min(K, 20)) + 1

    # Cap degree to K to prevent infinite loop when degree > K
    degree = min(degree, K)

    indices: set[int] = set()
    while len(indices) < degree:
        idx = prng.next() % K
        indices.add(idx)

    return frozenset(indices)
