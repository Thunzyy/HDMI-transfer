"""Cross-check the JavaScript-style BPC packing path against Python encoding."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from hdmi_transfer.core.config import PROFILES
from hdmi_transfer.core.protocols.encoding import (
    DECODE_THRESHOLDS,
    bytes_to_pixels,
    pixels_to_bytes,
)

_BPC_LEVELS_JS = {
    1: [0, 255],
    2: [0, 85, 170, 255],
    3: [0, 36, 73, 109, 146, 182, 219, 255],
}


def _encode_js_symbol_stream(frame_bytes: np.ndarray, *, rows: int, cols: int, bpc: int) -> np.ndarray:
    total_vals = rows * cols * 3
    vals_js = np.zeros(total_vals, dtype=np.uint8)
    bit_buf = 0
    bits_left = 0
    mask = (1 << bpc) - 1
    byte_idx = 0
    p = 0

    while p < total_vals:
        while bits_left < bpc and byte_idx < len(frame_bytes):
            bit_buf = (bit_buf << 8) | int(frame_bytes[byte_idx])
            byte_idx += 1
            bits_left += 8
        if bits_left < bpc:
            break
        bits_left -= bpc
        vals_js[p] = (bit_buf >> bits_left) & mask
        p += 1

    return vals_js


def _build_js_pixel_grid(vals_js: np.ndarray, *, rows: int, cols: int, bpc: int) -> np.ndarray:
    pixel_grid_js = np.zeros((rows, cols, 3), dtype=np.uint8)
    levels = _BPC_LEVELS_JS[bpc]
    vi = 0
    for r in range(rows):
        for c in range(cols):
            pixel_grid_js[r, c, 0] = levels[vals_js[vi]]
            vi += 1
            pixel_grid_js[r, c, 1] = levels[vals_js[vi]]
            vi += 1
            pixel_grid_js[r, c, 2] = levels[vals_js[vi]]
            vi += 1
    return pixel_grid_js


def test_js_bpc_symbol_stream_matches_python_multibpc_encoding() -> None:
    profile_base = PROFILES["balanced"]
    rows, cols = profile_base.rows, profile_base.cols
    blocks = profile_base.blocks_per_frame

    for bpc in (2, 3):
        profile = replace(profile_base, bits_per_channel=bpc)
        total_bytes = profile.bits_per_frame // 8
        rng = np.random.RandomState(42)
        frame_bytes = rng.randint(0, 256, size=total_bytes, dtype=np.uint8)

        vals_js = _encode_js_symbol_stream(frame_bytes, rows=rows, cols=cols, bpc=bpc)
        grid_py = bytes_to_pixels(frame_bytes.tobytes(), blocks, rows, cols, bpc)

        thresholds = DECODE_THRESHOLDS[bpc]
        symbols_py = np.digitize(grid_py.reshape(-1), thresholds).astype(np.uint8)

        assert np.array_equal(vals_js, symbols_py), f"symbol mismatch for bpc={bpc}"

        pixel_grid_js = _build_js_pixel_grid(vals_js, rows=rows, cols=cols, bpc=bpc)
        assert np.array_equal(pixel_grid_js, grid_py), f"pixel grid mismatch for bpc={bpc}"

        recovered_js = pixels_to_bytes(pixel_grid_js, bpc)
        recovered_py = pixels_to_bytes(grid_py, bpc)
        original = frame_bytes.tobytes()

        assert recovered_js[:total_bytes] == original, f"JS decode mismatch for bpc={bpc}"
        assert recovered_py[:total_bytes] == original, f"Python decode mismatch for bpc={bpc}"
