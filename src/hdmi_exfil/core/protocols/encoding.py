"""Multi-level bits-per-channel encoding/decoding helpers.

Shared by both sequential and fountain protocols.
"""

from __future__ import annotations

import numpy as np

# Pre-computed encode levels and decode thresholds for each bpc setting.
# Encode levels: the pixel values used to represent each N-bit symbol.
# Decode thresholds: midpoints between levels for np.digitize.

ENCODE_LEVELS: dict[int, np.ndarray] = {
    1: np.array([0, 255], dtype=np.uint8),
    2: np.array([0, 85, 170, 255], dtype=np.uint8),
    3: np.array([0, 36, 73, 109, 146, 182, 219, 255], dtype=np.uint8),
}

DECODE_THRESHOLDS: dict[int, np.ndarray] = {
    1: np.array([128], dtype=np.uint8),
    2: np.array([43, 128, 213], dtype=np.uint8),
    3: np.array([18, 55, 91, 128, 164, 200, 237], dtype=np.uint8),
}


def bytes_to_pixels(
    data: bytes,
    blocks_per_frame: int,
    rows: int,
    cols: int,
    bpc: int,
) -> np.ndarray:
    """Convert raw bytes to a (rows, cols, 3) uint8 pixel grid.

    Each block encodes 3*bpc bits (bpc bits per R/G/B channel).
    """
    levels = ENCODE_LEVELS[bpc]
    total_values = blocks_per_frame * 3  # one value per channel per block

    byte_arr = np.frombuffer(data, dtype=np.uint8)
    bits = np.unpackbits(byte_arr)

    total_bits = total_values * bpc
    if len(bits) < total_bits:
        bits = np.pad(bits, (0, total_bits - len(bits)), "constant")

    if bpc == 1:
        values = bits[:total_bits]
    else:
        # Group bits into bpc-sized chunks and convert to integer symbols
        bit_groups = bits[:total_bits].reshape(-1, bpc)
        # MSB first: [b0, b1] for bpc=2 → b0*2 + b1
        weights = (1 << np.arange(bpc - 1, -1, -1)).astype(np.uint8)
        values = (bit_groups * weights).sum(axis=1).astype(np.uint8)

    # Map symbol values to pixel levels
    pixel_values = levels[values].reshape(rows, cols, 3)
    return pixel_values


def pixels_to_bytes(sampled_grid: np.ndarray, bpc: int) -> bytes:
    """Convert a (rows, cols, 3) uint8 sampled pixel grid back to bytes.

    Applies multi-level quantization based on bpc, then packs to bytes.
    The input grid should already be in RGB order (caller flips BGR→RGB).
    """
    thresholds = DECODE_THRESHOLDS[bpc]
    flat = sampled_grid.reshape(-1)  # flatten all channels

    if bpc == 1:
        bits = (flat > thresholds[0]).astype(np.uint8)
    else:
        # np.digitize returns bin indices: 0..len(thresholds)
        symbols = np.digitize(flat, thresholds).astype(np.uint8)
        # Convert each symbol back to bpc bits (MSB first)
        bits = np.zeros(len(symbols) * bpc, dtype=np.uint8)
        for i in range(bpc):
            shift = bpc - 1 - i
            bits[i::bpc] = (symbols >> shift) & 1

    return np.packbits(bits).tobytes()
