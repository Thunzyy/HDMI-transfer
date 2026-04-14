"""Numba-accelerated XOR operations for fountain code hot paths.

Provides @njit-compiled XOR that operates on numpy uint8 arrays,
replacing pure Python byte-by-byte loops in FountainDecoder.
"""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(nogil=True)
def xor_into(dst: np.ndarray, src: np.ndarray) -> None:
    """XOR src into dst in-place. Both must be uint8 arrays of equal length.

    Releases the GIL during execution (nogil=True) to allow concurrent
    capture thread operation.
    """
    for i in range(len(dst)):
        dst[i] ^= src[i]


def warmup() -> None:
    """Trigger Numba compilation with tiny dummy arrays.

    Call during initialization to avoid first-call latency (1-3s)
    during actual decoding.
    """
    _dummy = np.zeros(16, dtype=np.uint8)
    xor_into(_dummy, np.zeros(16, dtype=np.uint8))
