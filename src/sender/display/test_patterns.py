"""Deterministic calibration test pattern generator.

Provides functions for generating checkerboard test patterns and computing
signal-to-noise ratio (SNR) and alignment offset from captured frames.  All
patterns use only pure black (0,0,0) and white (255,255,255) to survive chroma
subsampling (4:2:0, 4:2:2) without degradation.
"""

from __future__ import annotations

import math

import numpy as np

from hdmi_exfil.core.config import ResolutionProfile


def generate_checkerboard(profile: ResolutionProfile) -> np.ndarray:
    """Generate a checkerboard calibration pattern for *profile*.

    Each block in the encoding grid is either pure white (255,255,255) or pure
    black (0,0,0).  Block at grid position ``(row, col)`` is white when
    ``(row + col) % 2 == 0``, black otherwise.

    The pattern encodes a known bit sequence: alternating 0b111 and 0b000 in
    the 3bpp encoding, making it robust to chroma subsampling.

    Parameters
    ----------
    profile:
        Resolution profile defining width, height, and block_size.

    Returns
    -------
    np.ndarray
        Frame of shape ``(height, width, 3)`` uint8.
    """
    rows = profile.rows
    cols = profile.cols
    bs = profile.block_size

    # Build the block-level pattern: (rows, cols) boolean
    row_idx = np.arange(rows)[:, None]
    col_idx = np.arange(cols)[None, :]
    white_mask = ((row_idx + col_idx) % 2 == 0)  # (rows, cols)

    # Create block grid (rows, cols, 3) with 0 or 255
    white_val = np.array([255, 255, 255], dtype=np.uint8)
    black_val = np.array([0, 0, 0], dtype=np.uint8)
    grid = np.where(white_mask[:, :, None], white_val, black_val)

    # Upscale to full resolution via repeat (nearest-neighbour, no cv2 needed)
    frame = np.repeat(np.repeat(grid, bs, axis=0), bs, axis=1)

    # Trim to exact profile dimensions (in case rows*bs > height, etc.)
    frame = frame[: profile.height, : profile.width, :]

    return frame.astype(np.uint8)


def generate_known_payload(
    profile: ResolutionProfile,
) -> tuple[np.ndarray, bytes]:
    """Generate a frame encoding a known 0xAA payload.

    Uses ``SequentialProtocol`` to encode a repeating ``0xAA`` byte pattern
    that fills the frame payload.  Returns both the encoded image and the
    expected decoded payload bytes for comparison.

    Parameters
    ----------
    profile:
        Resolution profile for encoding.

    Returns
    -------
    tuple[np.ndarray, bytes]
        ``(frame_image, expected_payload)`` where *frame_image* is
        ``(height, width, 3)`` uint8 and *expected_payload* is the raw bytes
        that a correct decode should recover.
    """
    from hdmi_exfil.core.protocols.sequential import SequentialProtocol

    proto = SequentialProtocol(profile=profile)
    payload_size = profile.seq_bytes_per_frame
    payload = bytes([0xAA] * payload_size)
    frame = proto.encode_frame(payload, 0, 1)
    return frame, payload


def compute_snr(
    captured: np.ndarray,
    expected: np.ndarray,
    block_size: int,
) -> float:
    """Compute signal-to-noise ratio between *captured* and *expected* frames.

    Samples block centres from both frames, splits into "should be white" and
    "should be black" populations based on the expected values, then computes
    SNR in decibels.

    Parameters
    ----------
    captured:
        Captured frame ``(H, W, 3)`` uint8.
    expected:
        Reference frame ``(H, W, 3)`` uint8 (same dimensions as *captured*).
    block_size:
        Pixel size of each encoding block.

    Returns
    -------
    float
        SNR in dB.  Returns 60.0 for a perfect capture (noise < 1e-6).
    """
    half = block_size // 2

    # Sample block centres from both frames
    cap_centres = captured[half::block_size, half::block_size].astype(np.float64)
    exp_centres = expected[half::block_size, half::block_size].astype(np.float64)

    # Flatten to 1-D luminance (mean across RGB channels)
    cap_lum = cap_centres.mean(axis=-1).ravel()
    exp_lum = exp_centres.mean(axis=-1).ravel()

    # Split into white / black populations based on expected
    white_mask = exp_lum > 128.0
    black_mask = ~white_mask

    if white_mask.sum() == 0 or black_mask.sum() == 0:
        return 60.0  # degenerate: single-colour pattern

    white_pop = cap_lum[white_mask]
    black_pop = cap_lum[black_mask]

    signal = np.mean(white_pop) - np.mean(black_pop)
    noise = (np.std(white_pop) + np.std(black_pop)) / 2.0

    if noise < 1e-6:
        return 60.0  # perfect capture

    return float(20.0 * math.log10(abs(signal) / noise))


def compute_alignment(
    captured: np.ndarray,
    expected: np.ndarray,
) -> tuple[int, int]:
    """Compute pixel alignment offset between *captured* and *expected* frames.

    Uses template matching (``cv2.matchTemplate``) on central crops of both
    frames (converted to grayscale) to find the best-matching offset.

    Parameters
    ----------
    captured:
        Captured frame ``(H, W, 3)`` uint8.
    expected:
        Reference frame ``(H, W, 3)`` uint8 (same or larger dimensions).

    Returns
    -------
    tuple[int, int]
        ``(offset_x, offset_y)`` in pixels.
    """
    import cv2

    # Convert to grayscale
    if captured.ndim == 3:
        cap_gray = cv2.cvtColor(captured, cv2.COLOR_BGR2GRAY)
    else:
        cap_gray = captured

    if expected.ndim == 3:
        exp_gray = cv2.cvtColor(expected, cv2.COLOR_BGR2GRAY)
    else:
        exp_gray = expected

    # Crop a central region of the expected frame as template
    h, w = exp_gray.shape[:2]
    margin_y = h // 4
    margin_x = w // 4
    template = exp_gray[margin_y : h - margin_y, margin_x : w - margin_x]

    # Run template matching on captured frame
    result = cv2.matchTemplate(cap_gray, template, cv2.TM_CCOEFF_NORMED)
    _, _, _, max_loc = cv2.minMaxLoc(result)

    # The best match location in captured corresponds to where the template
    # starts.  The expected template was extracted from (margin_x, margin_y),
    # so offset = match_location - (margin_x, margin_y).
    offset_x = max_loc[0] - margin_x
    offset_y = max_loc[1] - margin_y

    return (int(offset_x), int(offset_y))
