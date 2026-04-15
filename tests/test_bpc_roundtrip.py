"""Comprehensive roundtrip tests for multi-BPC encoding.

Tests:
1. encoding.py bytes_to_pixels/pixels_to_bytes roundtrip
2. Full protocol encode/decode roundtrip (sequential + fountain)
3. JS sender simulation -> Python decode (cross-language validation)
"""

import struct
import sys
import zlib

import numpy as np

from hdmi_transfer.core.config import PROFILES, ResolutionProfile
from hdmi_transfer.core.protocols.encoding import (
    DECODE_THRESHOLDS,
    ENCODE_LEVELS,
    bytes_to_pixels,
    pixels_to_bytes,
)


def test_encoding_roundtrip():
    """Test bytes_to_pixels -> pixels_to_bytes roundtrip for each bpc."""
    profile_base = PROFILES["balanced"]
    rows, cols = profile_base.rows, profile_base.cols
    blocks = profile_base.blocks_per_frame

    print("=== encoding.py roundtrip ===")
    for bpc in (1, 2, 3):
        from dataclasses import replace
        profile = replace(profile_base, bits_per_channel=bpc)
        total_bytes = profile.bits_per_frame // 8

        # Random data
        rng = np.random.RandomState(42)
        data = rng.randint(0, 256, size=total_bytes, dtype=np.uint8).tobytes()

        # Encode
        grid = bytes_to_pixels(data, blocks, rows, cols, bpc)
        assert grid.shape == (rows, cols, 3), f"bpc={bpc}: shape {grid.shape}"

        # Verify pixel values are valid levels
        levels = ENCODE_LEVELS[bpc]
        unique = np.unique(grid)
        for v in unique:
            assert v in levels, f"bpc={bpc}: invalid pixel value {v}"

        # Decode
        recovered = pixels_to_bytes(grid, bpc)

        # Compare
        if recovered[:total_bytes] == data:
            print(f"  bpc={bpc}: OK ({total_bytes} bytes roundtrip)")
        else:
            # Find first mismatch
            for i in range(min(len(recovered), total_bytes)):
                if recovered[i] != data[i]:
                    assert recovered[i] == data[i], (
                        f"bpc={bpc}: byte {i} mismatch: "
                        f"expected {data[i]:02x}, got {recovered[i]:02x}"
                    )
                    break
            assert len(recovered) >= total_bytes, (
                f"bpc={bpc}: recovered length {len(recovered)} < {total_bytes}"
            )


def test_sequential_roundtrip():
    """Test full sequential protocol encode/decode roundtrip."""
    from dataclasses import replace
    from hdmi_transfer.core.protocols.sequential import SequentialProtocol
    from hdmi_transfer.core.config import FRAME_TYPE_DATA, SEQ_MAGIC

    profile_base = PROFILES["balanced"]

    print("\n=== Sequential protocol roundtrip ===")
    for bpc in (1, 2, 3):
        profile = replace(profile_base, bits_per_channel=bpc)
        proto = SequentialProtocol(profile)

        # Create test payload
        payload_size = profile.seq_bytes_per_frame
        rng = np.random.RandomState(42)
        payload = rng.randint(0, 256, size=payload_size, dtype=np.uint8).tobytes()

        # Encode frame
        img = proto.encode_frame(payload, frame_index=5, total_frames=10)

        # img is BGR (OpenCV format). Simulate capture: sample block centers
        from hdmi_transfer.core.capture.sampler import sample_frame
        sampled = sample_frame(img, profile.rows, profile.cols, profile.block_size)

        # Decode
        result = proto.decode_frame(sampled)

        if result.is_valid and result.data == payload:
            print(f"  bpc={bpc}: OK (payload={payload_size} B, frame_idx={result.frame_index})")
        else:
            assert result.is_valid, f"bpc={bpc}: sequential decode returned invalid"
            assert result.data == payload, f"bpc={bpc}: sequential payload mismatch"


def test_fountain_roundtrip():
    """Test full fountain protocol encode/decode roundtrip."""
    from dataclasses import replace
    from hdmi_transfer.core.protocols.fountain import FountainProtocol

    profile_base = PROFILES["balanced"]

    print("\n=== Fountain protocol roundtrip ===")
    for bpc in (1, 2, 3):
        profile = replace(profile_base, bits_per_channel=bpc)
        proto = FountainProtocol(profile)

        # Create test payload
        payload_size = proto.bytes_per_frame
        rng = np.random.RandomState(42)
        payload = rng.randint(0, 256, size=payload_size, dtype=np.uint8).tobytes()

        # Encode frame
        img = proto.encode_frame(payload, frame_index=1, total_frames=10, seed=42)

        # Simulate capture
        from hdmi_transfer.core.capture.sampler import sample_frame
        sampled = sample_frame(img, profile.rows, profile.cols, profile.block_size)

        # Decode
        result = proto.decode_frame(sampled)

        if result.is_valid and result.data == payload:
            print(f"  bpc={bpc}: OK (payload={payload_size} B, seed={result.frame_index})")
        else:
            mismatch = sum(1 for a, b in zip(result.data, payload) if a != b)
            assert result.is_valid, f"bpc={bpc}: fountain decode returned invalid"
            assert result.data == payload, (
                f"bpc={bpc}: fountain payload mismatch ({mismatch} mismatches)"
            )


def test_js_sender_simulation():
    """Simulate JS sender bytesToValues/drawValues -> Python pixels_to_bytes.

    This tests the cross-language path: JS canvas -> HDMI -> Python decoder.
    """
    from dataclasses import replace

    profile_base = PROFILES["balanced"]
    BPC_LEVELS_JS = {
        1: [0, 255],
        2: [0, 85, 170, 255],
        3: [0, 36, 73, 109, 146, 182, 219, 255],
    }

    print("\n=== JS sender simulation -> Python decode ===")
    for bpc in (1, 2, 3):
        profile = replace(profile_base, bits_per_channel=bpc)
        rows, cols = profile.rows, profile.cols
        total_bytes = profile.bits_per_frame // 8
        levels = BPC_LEVELS_JS[bpc]

        # Random frame bytes (as the sender would generate)
        rng = np.random.RandomState(42)
        frame_bytes = rng.randint(0, 256, size=total_bytes, dtype=np.uint8)

        # --- Simulate JS bytesToValues ---
        total_vals = rows * cols * 3
        vals = np.zeros(total_vals, dtype=np.uint8)

        if bpc == 1:
            p = 0
            for byte in frame_bytes:
                for shift in range(7, -1, -1):
                    vals[p] = (byte >> shift) & 1
                    p += 1
        else:
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
                    vals[p] = (bit_buf >> bits_left) & mask
                    p += 1
                else:
                    break

        # --- Simulate JS drawValues (create pixel grid) ---
        pixel_grid = np.zeros((rows, cols, 3), dtype=np.uint8)
        vi = 0
        for r in range(rows):
            for c in range(cols):
                pixel_grid[r, c, 0] = levels[vals[vi]]; vi += 1  # R
                pixel_grid[r, c, 1] = levels[vals[vi]]; vi += 1  # G
                pixel_grid[r, c, 2] = levels[vals[vi]]; vi += 1  # B

        # --- Python decode (as receiver would do) ---
        # The receiver gets RGB grid after BGR->RGB flip
        # In our simulation, pixel_grid is already RGB
        recovered = pixels_to_bytes(pixel_grid, bpc)

        if recovered[:total_bytes] == frame_bytes.tobytes():
            print(f"  bpc={bpc}: OK (JS->Python {total_bytes} bytes)")
        else:
            mismatch = sum(1 for a, b in zip(recovered, frame_bytes.tobytes()) if a != b)
            assert recovered[:total_bytes] == frame_bytes.tobytes(), (
                f"bpc={bpc}: JS sender simulation mismatch ({mismatch} mismatches)"
            )


def test_noise_resilience():
    """Test decode accuracy with added Gaussian noise (simulating HDMI signal)."""
    from dataclasses import replace

    profile_base = PROFILES["balanced"]
    rows, cols = profile_base.rows, profile_base.cols
    blocks = profile_base.blocks_per_frame

    print("\n=== Noise resilience test ===")
    for bpc in (1, 2, 3):
        profile = replace(profile_base, bits_per_channel=bpc)
        total_bytes = profile.bits_per_frame // 8

        rng = np.random.RandomState(42)
        data = rng.randint(0, 256, size=total_bytes, dtype=np.uint8).tobytes()

        grid = bytes_to_pixels(data, blocks, rows, cols, bpc)

        # Add noise at different levels
        for noise_std in (5, 10, 15, 20, 30):
            noise = rng.normal(0, noise_std, grid.shape).astype(np.int16)
            noisy = np.clip(grid.astype(np.int16) + noise, 0, 255).astype(np.uint8)
            recovered = pixels_to_bytes(noisy, bpc)

            n_total = total_bytes
            n_correct = sum(1 for a, b in zip(recovered[:n_total], data) if a == b)
            pct = n_correct / n_total * 100
            ok = "OK" if pct == 100 else f"DEGRADED"
            print(f"  bpc={bpc} noise_std={noise_std:2d}: {pct:6.2f}% correct ({ok})")


def test_crc32_compatibility():
    """Test that Python zlib.crc32 matches the expected CRC32 for fountain frames."""
    print("\n=== CRC32 compatibility ===")

    # Known test vector
    data = b"Hello, World!"
    py_crc = zlib.crc32(data) & 0xFFFFFFFF
    # Standard CRC32 of "Hello, World!" should be 0xEC4AC3D0
    expected = 0xEC4AC3D0
    if py_crc == expected:
        print(f"  CRC32 test vector: OK ({py_crc:#010x})")
    else:
        assert py_crc == expected, (
            f"CRC32 mismatch: got {py_crc:#010x}, expected {expected:#010x}"
        )


if __name__ == "__main__":
    ok = True
    ok &= test_encoding_roundtrip()
    ok &= test_sequential_roundtrip()
    ok &= test_fountain_roundtrip()
    ok &= test_js_sender_simulation()
    test_noise_resilience()
    test_crc32_compatibility()

    print("\n" + ("=" * 50))
    if ok:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    sys.exit(0 if ok else 1)
