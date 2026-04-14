"""Unified block-centre sampling for captured HDMI frames.

Extracts the centre pixel of each encoding block from a raw video frame.
Handles both the simple case (no offset, no scaling -- as in receiver.py)
and the calibrated case (offset + scale -- as in receiver_fountain.py).

The function is *pure*: grid dimensions are explicit parameters so that the
module has no dependency on ``hdmi_exfil.config``.
"""

from __future__ import annotations

import numpy as np


def sample_frame(
    frame: np.ndarray,
    rows: int,
    cols: int,
    block_size: int,
    offset_x: int = 0,
    offset_y: int = 0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> np.ndarray:
    """Sample block centres from *frame* and return a ``(rows, cols, 3)`` grid.

    When all offset/scale parameters are at their defaults (0 / 1.0), the
    output is identical to the simple ``frame[half::bs, half::bs][:R, :C]``
    slice used by ``receiver.py``.  When offset or scale are non-default, the
    more general ``np.arange`` + broadcasting path from
    ``receiver_fountain.py`` is used.

    Parameters
    ----------
    frame:
        Raw captured frame, shape ``(H, W, 3)`` uint8.
    rows, cols:
        Number of encoding rows / columns in the grid.
    block_size:
        Pixel width (and height) of each encoding block.
    offset_x, offset_y:
        Pixel offset applied *before* scaling (calibration shift).
    scale_x, scale_y:
        Multiplicative scaling factor for block spacing.

    Returns
    -------
    np.ndarray
        Sampled grid of shape ``(rows, cols, 3)`` uint8.
    """
    expected_h = rows * block_size
    expected_w = cols * block_size

    # Resize frame to expected dimensions if necessary
    if frame.shape[0] != expected_h or frame.shape[1] != expected_w:
        # Nearest-neighbor resize using numpy indexing (no cv2 dependency)
        src_h, src_w = frame.shape[:2]
        row_idx = np.linspace(0, src_h - 1, expected_h, dtype=int)
        col_idx = np.linspace(0, src_w - 1, expected_w, dtype=int)
        frame = frame[row_idx[:, None], col_idx[None, :]]

    half_block = block_size // 2

    # Compute sample coordinates via arange + broadcasting (general path).
    grid_x = np.arange(cols)
    sample_x = (grid_x * block_size * scale_x + offset_x + half_block).astype(int)

    grid_y = np.arange(rows)
    sample_y = (grid_y * block_size * scale_y + offset_y + half_block).astype(int)

    # Clip to frame bounds
    np.clip(sample_x, 0, frame.shape[1] - 1, out=sample_x)
    np.clip(sample_y, 0, frame.shape[0] - 1, out=sample_y)

    # Advanced indexing: frame[sample_y[:, None], sample_x] -> (rows, cols, 3)
    sampled: np.ndarray = frame[sample_y[:, None], sample_x]

    return sampled
