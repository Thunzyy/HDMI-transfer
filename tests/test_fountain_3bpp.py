"""Round-trip tests for 3bpp fountain encoding.

Verifies that the upgraded FountainProtocol correctly encodes and decodes
data using 3 bits per block (RGB binary), and that the full fountain
pipeline (encode -> sample -> decode -> peel) recovers original data.
"""

import struct
import zlib

import numpy as np

from hdmi_exfil import config
from hdmi_exfil.capture.sampler import sample_frame
from hdmi_exfil.protocols.fountain import (
    FOUNT_HEADER_CURRENT_SIZE,
    FOUNT_HEADER_V1_FMT,
    FOUNT_HEADER_V1_PRE_CRC,
    FOUNT_HEADER_V1_SIZE,
    FOUNTAIN_BYTES_PER_FRAME,
    FountainDecoder,
    FountainProtocol,
    PAYLOAD_SIZE,
)


def test_3bpp_capacity_constants():
    """Verify 3bpp capacity constants are 3x the old 1bpp values."""
    # Old 1bpp values: FOUNTAIN_BYTES_PER_FRAME=4050.
    # New 3bpp values: 3x capacity.
    assert FOUNTAIN_BYTES_PER_FRAME == 12150, (
        f"Expected 12150, got {FOUNTAIN_BYTES_PER_FRAME}"
    )
    assert FOUNT_HEADER_CURRENT_SIZE == 16, (
        f"Expected v2 fountain header size=16, got {FOUNT_HEADER_CURRENT_SIZE}"
    )
    assert PAYLOAD_SIZE == 12134, (
        f"Expected 12134, got {PAYLOAD_SIZE}"
    )

    # Verify derivation from config
    expected_bytes = (config.ROWS * config.COLS * 3) // 8
    assert FOUNTAIN_BYTES_PER_FRAME == expected_bytes
    assert PAYLOAD_SIZE == expected_bytes - FOUNT_HEADER_CURRENT_SIZE


def test_3bpp_encode_frame_shape():
    """Verify encode_frame returns correct shape with binary RGB values."""
    proto = FountainProtocol()
    data = np.random.RandomState(42).bytes(PAYLOAD_SIZE)

    frame = proto.encode_frame(data, frame_index=0, total_frames=1, seed=100)

    # Shape must be (HEIGHT, WIDTH, 3) uint8
    assert frame.shape == (config.HEIGHT, config.WIDTH, 3), (
        f"Expected ({config.HEIGHT}, {config.WIDTH}, 3), got {frame.shape}"
    )
    assert frame.dtype == np.uint8

    # All pixel values must be exactly 0 or 255 (binary RGB)
    unique_values = np.unique(frame)
    assert set(unique_values).issubset({0, 255}), (
        f"Expected only 0 and 255, got {unique_values}"
    )


def test_3bpp_encode_decode_roundtrip():
    """Encode a payload, sample the frame, decode -- verify payload recovery."""
    proto = FountainProtocol()
    rng = np.random.RandomState(123)
    original_payload = rng.bytes(PAYLOAD_SIZE)

    # Encode with known seed and K
    seed = 42
    K = 1
    expected_droplets = 777
    frame_img = proto.encode_frame(
        original_payload,
        frame_index=0,
        total_frames=K,
        seed=seed,
        expected_droplets=expected_droplets,
    )

    # Sample (downscale back to block grid)
    sampled = sample_frame(
        frame_img, config.ROWS, config.COLS, config.BLOCK_SIZE,
    )

    # Decode
    result = proto.decode_frame(sampled)

    assert result.is_valid, "decode_frame should return valid result"
    assert result.frame_index == seed, (
        f"Expected seed={seed}, got {result.frame_index}"
    )
    assert result.total_frames == K, (
        f"Expected K={K}, got {result.total_frames}"
    )
    assert result.max_frames == expected_droplets
    assert result.data is not None

    # The decoded payload should match the original
    # (result.data may be longer due to frame padding; compare the prefix)
    recovered_payload = result.data[:PAYLOAD_SIZE]
    assert recovered_payload == original_payload, (
        "Round-trip payload mismatch"
    )


def test_3bpp_fountain_full_roundtrip():
    """Full pipeline: encode N droplets -> decode each -> peel -> recover.

    Uses small K=5 with K+5 droplets to ensure the decoder completes.
    This is the critical end-to-end test for 3bpp fountain correctness.
    """
    proto = FountainProtocol()
    rng = np.random.RandomState(999)

    K = 5
    # Build K chunks of random data
    chunks = [rng.bytes(PAYLOAD_SIZE) for _ in range(K)]

    # Concatenate all chunks as the "original file data"
    original_data = b"".join(chunks)

    # Create FountainDecoder
    decoder = FountainDecoder(total_chunks=K, payload_size=PAYLOAD_SIZE)

    # Send K + 15 droplets (extra to handle degree > 1 droplets)
    max_droplets = K + 15
    seed = 1

    from hdmi_exfil.prng import choose_indices

    for _ in range(max_droplets):
        if decoder.is_complete():
            break

        # Build droplet payload by XOR-ing selected chunks (RSD via choose_indices)
        indices = choose_indices(seed, K)

        droplet_data = bytearray(PAYLOAD_SIZE)
        for idx in indices:
            chunk_bytes = chunks[idx]
            for i in range(PAYLOAD_SIZE):
                droplet_data[i] ^= chunk_bytes[i]

        # Encode the droplet as a 3bpp frame
        frame_img = proto.encode_frame(
            bytes(droplet_data),
            frame_index=seed,
            total_frames=K,
            seed=seed,
            expected_droplets=max_droplets,
        )

        # Sample the frame (simulate perfect capture)
        sampled = sample_frame(
            frame_img, config.ROWS, config.COLS, config.BLOCK_SIZE,
        )

        # Decode the frame
        result = proto.decode_frame(sampled)
        assert result.is_valid, (
            f"Droplet seed={seed} failed to decode"
        )
        assert result.frame_index == seed
        assert result.total_frames == K
        assert result.max_frames == max_droplets

        # Feed decoded payload into the fountain decoder
        decoder.add_droplet(seed, bytearray(result.data[:PAYLOAD_SIZE]))
        seed += 1

    assert decoder.is_complete(), (
        f"Decoder incomplete after {seed - 1} droplets "
        f"(recovered {len(decoder.chunks)}/{K} chunks)"
    )

    # Recover and verify
    recovered = decoder.get_file_data()
    recovered_data = bytes(recovered[: len(original_data)])
    assert recovered_data == original_data, (
        "Full fountain pipeline failed: recovered data does not match original"
    )


def test_3bpp_decode_legacy_v1_header(monkeypatch):
    """Decoder accepts legacy v1 fountain frames (no max_droplets field)."""
    proto = FountainProtocol()
    seed = 1337
    k = 5
    payload = np.random.RandomState(2026).bytes(FOUNTAIN_BYTES_PER_FRAME - FOUNT_HEADER_V1_SIZE)

    header_pre = struct.pack(FOUNT_HEADER_V1_FMT, config.FOUNTAIN_MAGIC, seed, k)
    crc = zlib.crc32(header_pre + payload) & 0xFFFFFFFF
    raw = header_pre + struct.pack(">I", crc) + payload

    monkeypatch.setattr(
        "hdmi_exfil.core.protocols.encoding.pixels_to_bytes",
        lambda _grid, _bpc: raw,
    )

    sampled = np.zeros((config.ROWS, config.COLS, 3), dtype=np.uint8)
    result = proto.decode_frame(sampled)
    assert result.is_valid
    assert result.frame_index == seed
    assert result.total_frames == k
    assert result.max_frames is None
    assert result.data == payload
