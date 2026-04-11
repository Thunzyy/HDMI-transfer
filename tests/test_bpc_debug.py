"""Debug the JS->Python bpc=2 mismatch."""

import numpy as np
from hdmi_exfil.core.config import PROFILES
from hdmi_exfil.core.protocols.encoding import (
    ENCODE_LEVELS, DECODE_THRESHOLDS,
    bytes_to_pixels, pixels_to_bytes,
)
from dataclasses import replace

profile_base = PROFILES["balanced"]
rows, cols = profile_base.rows, profile_base.cols
blocks = profile_base.blocks_per_frame

BPC_LEVELS_JS = {
    1: [0, 255],
    2: [0, 85, 170, 255],
    3: [0, 36, 73, 109, 146, 182, 219, 255],
}

for bpc in (2, 3):
    profile = replace(profile_base, bits_per_channel=bpc)
    total_bytes = profile.bits_per_frame // 8
    levels = BPC_LEVELS_JS[bpc]

    rng = np.random.RandomState(42)
    frame_bytes = rng.randint(0, 256, size=total_bytes, dtype=np.uint8)

    total_vals = rows * cols * 3

    # JS simulation (FIXED: outer loop only checks p < totalVals)
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
        if bits_left >= bpc:
            bits_left -= bpc
            vals_js[p] = (bit_buf >> bits_left) & mask
            p += 1
        else:
            break

    # Python encoding
    grid_py = bytes_to_pixels(frame_bytes.tobytes(), blocks, rows, cols, bpc)
    vals_py = grid_py.reshape(-1)  # pixel values

    # Decode vals_py to symbols
    thresholds = DECODE_THRESHOLDS[bpc]
    symbols_py = np.digitize(vals_py, thresholds).astype(np.uint8)

    # Compare symbol arrays
    if not np.array_equal(vals_js, symbols_py):
        diffs = np.where(vals_js != symbols_py)[0]
        print(f"bpc={bpc}: {len(diffs)} symbol mismatches at indices: {diffs[:20]}")
        for i in diffs[:5]:
            print(f"  idx {i}: JS={vals_js[i]} Python_pixel={vals_py[i]} Python_symbol={symbols_py[i]}")
    else:
        print(f"bpc={bpc}: symbols match perfectly")

    # Now build pixel grid from JS vals and decode
    pixel_grid_js = np.zeros((rows, cols, 3), dtype=np.uint8)
    vi = 0
    for r in range(rows):
        for c in range(cols):
            pixel_grid_js[r, c, 0] = levels[vals_js[vi]]; vi += 1
            pixel_grid_js[r, c, 1] = levels[vals_js[vi]]; vi += 1
            pixel_grid_js[r, c, 2] = levels[vals_js[vi]]; vi += 1

    recovered_js = pixels_to_bytes(pixel_grid_js, bpc)
    recovered_py = pixels_to_bytes(grid_py, bpc)

    # Compare byte-level
    n = total_bytes
    mismatches_js = []
    mismatches_py = []
    for i in range(n):
        if recovered_js[i] != frame_bytes[i]:
            mismatches_js.append(i)
        if recovered_py[i] != frame_bytes[i]:
            mismatches_py.append(i)

    print(f"bpc={bpc}: JS->decode mismatches: {len(mismatches_js)} at {mismatches_js[:10]}")
    print(f"bpc={bpc}: Py->decode mismatches: {len(mismatches_py)} at {mismatches_py[:10]}")

    if mismatches_js:
        i = mismatches_js[0]
        print(f"  Byte {i}: original=0x{frame_bytes[i]:02x} recovered=0x{recovered_js[i]:02x}")
        # Check the last byte area
        print(f"  Last 5 bytes original: {[f'0x{b:02x}' for b in frame_bytes[n-5:n]]}")
        print(f"  Last 5 bytes recovered: {[f'0x{b:02x}' for b in recovered_js[n-5:n]]}")

    # Also check if the symbol arrays give different pixel grids
    if not np.array_equal(pixel_grid_js, grid_py):
        pdiffs = np.where(pixel_grid_js.reshape(-1) != grid_py.reshape(-1))[0]
        print(f"bpc={bpc}: pixel grids differ at {len(pdiffs)} positions")
    else:
        print(f"bpc={bpc}: pixel grids match")

    # Check bit_buf overflow
    print(f"bpc={bpc}: bit_buf at end = {bit_buf}, bits_left = {bits_left}, byte_idx = {byte_idx}, p = {p}")
    print()
