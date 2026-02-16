"""Round-trip tests for 3bpp fountain encoding.

Verifies that the upgraded FountainProtocol correctly encodes and decodes
data using 3 bits per block (RGB binary), and that the full fountain
pipeline (encode -> sample -> decode -> peel) recovers original data.
"""

import numpy as np

from hdmi_exfil import config
from hdmi_exfil.capture.sampler import sample_frame
from hdmi_exfil.protocols.fountain import (
    FOUNTAIN_BYTES_PER_FRAME,
    FountainDecoder,
    FountainProtocol,
    PAYLOAD_SIZE,
)


def test_3bpp_capacity_constants():
    """Verify 3bpp capacity constants are 3x the old 1bpp values."""
    # Old 1bpp values: FOUNTAIN_BYTES_PER_FRAME=4050, PAYLOAD_SIZE=4038
    # New 3bpp values: 3x capacity
    assert FOUNTAIN_BYTES_PER_FRAME == 12150, (
        f"Expected 12150, got {FOUNTAIN_BYTES_PER_FRAME}"
    )
    assert PAYLOAD_SIZE == 12138, (
        f"Expected 12138, got {PAYLOAD_SIZE}"
    )

    # Verify derivation from config
    expected_bytes = (config.ROWS * config.COLS * 3) // 8
    assert FOUNTAIN_BYTES_PER_FRAME == expected_bytes


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
    frame_img = proto.encode_frame(
        original_payload, frame_index=0, total_frames=K, seed=seed,
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

    # Send K + 5 droplets (extra to handle degree > 1 droplets)
    max_droplets = K + 15
    seed = 1

    from hdmi_exfil.prng import PRNG

    for _ in range(max_droplets):
        if decoder.is_complete():
            break

        # Build droplet payload by XOR-ing selected chunks
        prng = PRNG(seed)
        degree = 1
        r = prng.next_float()
        if r < 0.1:
            degree = 1
        elif r < 0.6:
            degree = 2
        else:
            degree = int(prng.next_float() * min(K, 20)) + 1
        degree = min(degree, K)

        indices = set()
        while len(indices) < degree:
            idx = prng.next() % K
            indices.add(idx)

        droplet_data = bytearray(PAYLOAD_SIZE)
        for idx in indices:
            chunk_bytes = chunks[idx]
            for i in range(PAYLOAD_SIZE):
                droplet_data[i] ^= chunk_bytes[i]

        # Encode the droplet as a 3bpp frame
        frame_img = proto.encode_frame(
            bytes(droplet_data), frame_index=seed, total_frames=K, seed=seed,
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
