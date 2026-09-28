"""Tests for Numba-accelerated XOR operations and FountainDecoder integration.

Verifies xor_into correctness, identity properties, performance at scale,
and end-to-end integration with FountainDecoder using numpy arrays.
"""

import os

import numpy as np

from hdmi_transfer.core.protocols.xor_ops import warmup, xor_into
from hdmi_transfer.core.protocols.fountain import (
    FountainDecoder,
    PAYLOAD_SIZE,
)
from hdmi_transfer.core.prng import choose_indices


def test_xor_into_basic():
    """Verify XOR of known byte patterns produces correct results."""
    a = np.array([0xFF, 0x00, 0xAA, 0x55], dtype=np.uint8)
    b = np.array([0x0F, 0xF0, 0x55, 0xAA], dtype=np.uint8)
    xor_into(a, b)
    expected = np.array([0xF0, 0xF0, 0xFF, 0xFF], dtype=np.uint8)
    np.testing.assert_array_equal(a, expected)


def test_xor_into_identity():
    """XOR with zeros is identity; XOR with self produces zeros."""
    # XOR with zeros: identity
    original = np.array([1, 2, 3, 4, 5], dtype=np.uint8)
    a = original.copy()
    zeros = np.zeros(5, dtype=np.uint8)
    xor_into(a, zeros)
    np.testing.assert_array_equal(a, original)

    # XOR with self: zeros
    b = original.copy()
    xor_into(b, original)
    np.testing.assert_array_equal(b, np.zeros(5, dtype=np.uint8))


def test_xor_into_large_array():
    """XOR two PAYLOAD_SIZE-byte arrays, verify against numpy vectorized."""
    rng = np.random.RandomState(42)
    a = rng.randint(0, 256, size=PAYLOAD_SIZE, dtype=np.uint8)
    b = rng.randint(0, 256, size=PAYLOAD_SIZE, dtype=np.uint8)

    # Compute expected result with numpy vectorized XOR
    expected = a ^ b

    # Use xor_into (modifies a in-place)
    xor_into(a, b)
    np.testing.assert_array_equal(a, expected)


def test_fountain_decoder_with_numba():
    """Integration test: FountainDecoder with Numba XOR recovers data.

    Creates K chunks, builds droplets via PRNG, feeds to decoder,
    and verifies is_complete + get_file_data matches original.
    """
    K = 5
    rng = np.random.RandomState(999)

    # Build K chunks of random data
    chunks = [rng.bytes(PAYLOAD_SIZE) for _ in range(K)]
    original_data = b"".join(chunks)

    decoder = FountainDecoder(total_chunks=K, payload_size=PAYLOAD_SIZE)

    max_droplets = K + 15
    seed = 1

    for _ in range(max_droplets):
        if decoder.is_complete():
            break

        # Build droplet payload by XOR-ing selected chunks (matches decoder logic).
        indices = choose_indices(seed, K)

        droplet_data = bytearray(PAYLOAD_SIZE)
        for idx in indices:
            chunk_bytes = chunks[idx]
            for i in range(PAYLOAD_SIZE):
                droplet_data[i] ^= chunk_bytes[i]

        decoder.add_droplet(seed, bytes(droplet_data))
        seed += 1

    assert decoder.is_complete(), (
        f"Decoder incomplete after {seed - 1} droplets "
        f"(recovered {len(decoder.chunks)}/{K} chunks)"
    )

    # Verify chunks are stored as numpy arrays
    for chunk_idx, chunk in decoder.chunks.items():
        assert isinstance(chunk, np.ndarray), (
            f"Chunk {chunk_idx} is {type(chunk).__name__}, expected np.ndarray"
        )
        assert chunk.dtype == np.uint8

    # Verify recovered data matches original
    recovered = decoder.get_file_data()
    recovered_data = bytes(recovered[:len(original_data)])
    assert recovered_data == original_data


def test_warmup():
    """Call warmup() twice -- second call should succeed (already compiled)."""
    warmup()
    warmup()  # No error on second call (already JIT-compiled)
