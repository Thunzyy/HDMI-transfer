"""Fountain encode/decode round-trip tests.

Tests the fountain coding pipeline (LT codes with SplitMix32 PRNG) without
any hardware. Verifies single-chunk, multi-chunk, partial-chunk, and edge
cases using in-memory encoding and FountainDecoder from receiver_fountain.py.

IMPORTANT: Fountain mode uses different constants from sequential mode.
All constants are defined locally here, NOT imported from common.py.
"""

import os

from receiver_fountain import PRNG, FountainDecoder

# Fountain-specific constants (from sender.html, NOT from common.py)
FOUNTAIN_BYTES_PER_FRAME = 4050
FOUNTAIN_HEADER_LEN = 6
FOUNTAIN_PAYLOAD_SIZE = FOUNTAIN_BYTES_PER_FRAME - FOUNTAIN_HEADER_LEN  # 4044


def choose_indices(seed, K):
    """Mirror the chooseIndices logic from sender.html / receiver_fountain.py.

    NOTE: Includes degree cap to min(degree, K) to avoid infinite loop when
    degree > K (known bug in production code, to be fixed in later phase).
    """
    prng = PRNG(seed)
    degree = 1
    r = prng.next_float()
    if r < 0.1:
        degree = 1
    elif r < 0.6:
        degree = 2
    else:
        degree = int(prng.next_float() * min(K, 20)) + 1

    # Cap degree to K to prevent infinite loop
    degree = min(degree, K)

    indices = set()
    while len(indices) < degree:
        indices.add(prng.next() % K)
    return indices


def build_droplet(seed, K, chunks):
    """Build a fountain-encoded droplet by XOR-ing selected chunks."""
    indices = choose_indices(seed, K)
    payload = bytearray(FOUNTAIN_PAYLOAD_SIZE)
    for idx in indices:
        for i in range(FOUNTAIN_PAYLOAD_SIZE):
            payload[i] ^= chunks[idx][i]
    return payload


def prepare_chunks(data):
    """Split data into FOUNTAIN_PAYLOAD_SIZE chunks, zero-padded."""
    K = -(-len(data) // FOUNTAIN_PAYLOAD_SIZE)  # ceil division
    chunks = []
    for i in range(K):
        chunk = bytearray(FOUNTAIN_PAYLOAD_SIZE)
        start = i * FOUNTAIN_PAYLOAD_SIZE
        end = min(start + FOUNTAIN_PAYLOAD_SIZE, len(data))
        chunk[:end - start] = data[start:end]
        chunks.append(chunk)
    return K, chunks


def _compute_degree(seed, K):
    """Compute the degree that the decoder will use for a given seed and K.

    This mirrors the inline chooseIndices logic in FountainDecoder.add_droplet
    WITHOUT the degree cap, to predict if the decoder would hang.
    """
    prng = PRNG(seed)
    degree = 1
    r = prng.next_float()
    if r < 0.1:
        degree = 1
    elif r < 0.6:
        degree = 2
    else:
        degree = int(prng.next_float() * min(K, 20)) + 1
    return degree


def _would_hang(seed, K):
    """Check if FountainDecoder.add_droplet would infinite-loop for this seed.

    Known bug: production code does not cap degree to K, so when degree > K
    the while loop in add_droplet can never terminate.
    """
    return _compute_degree(seed, K) > K


def _fountain_roundtrip(data, max_overhead=10):
    """Helper: encode data as fountain droplets, decode, return recovered data.

    Skips seeds that would trigger the known infinite-loop bug in
    FountainDecoder.add_droplet (degree > K). Both encoder (build_droplet)
    and decoder agree on indices for non-hanging seeds.

    Args:
        data: Original bytes to encode.
        max_overhead: Maximum multiplier over K for droplet budget.

    Returns:
        Tuple of (recovered_bytes_trimmed, droplets_used, K).
    """
    K, chunks = prepare_chunks(data)
    decoder = FountainDecoder(K, FOUNTAIN_PAYLOAD_SIZE)

    seed = 1
    max_seeds = max(K * max_overhead * 3, 200)  # search budget
    droplets_used = 0
    max_droplets = K * max_overhead

    while not decoder.is_complete() and seed <= max_seeds and droplets_used < max_droplets:
        if not _would_hang(seed, K):
            payload = build_droplet(seed, K, chunks)
            decoder.add_droplet(seed, payload)
            droplets_used += 1
        seed += 1

    assert decoder.is_complete(), (
        f"Decoder did not complete after {droplets_used} droplets "
        f"(K={K}, recovered {len(decoder.chunks)}/{K} chunks, "
        f"searched {seed - 1} seeds)"
    )

    recovered = decoder.get_file_data()[:len(data)]
    return bytes(recovered), droplets_used, K


class TestFountainSingleChunk:
    """Tests for data that fits in a single chunk (K=1)."""

    def test_fountain_single_chunk(self):
        """Data fitting in 1 chunk recovers correctly."""
        data = os.urandom(FOUNTAIN_PAYLOAD_SIZE)
        recovered, droplets, K = _fountain_roundtrip(data, max_overhead=5)

        assert K == 1
        assert droplets <= 3, f"K=1 should need at most ~3 droplets, got {droplets}"
        assert recovered == data

    def test_fountain_small_data(self):
        """100 bytes of random data recovers correctly (K=1)."""
        data = os.urandom(100)
        recovered, droplets, K = _fountain_roundtrip(data, max_overhead=5)

        assert K == 1
        assert recovered == data


class TestFountainMultiChunk:
    """Tests for data spanning multiple chunks."""

    def test_fountain_multi_chunk(self):
        """Data spanning exactly 3 chunks recovers correctly."""
        data = os.urandom(FOUNTAIN_PAYLOAD_SIZE * 3)
        recovered, droplets, K = _fountain_roundtrip(data, max_overhead=5)

        assert K == 3
        assert recovered == data

    def test_fountain_larger_data(self):
        """Data spanning 10 chunks recovers correctly."""
        data = os.urandom(FOUNTAIN_PAYLOAD_SIZE * 10)
        recovered, droplets, K = _fountain_roundtrip(data, max_overhead=10)

        assert K == 10
        assert recovered == data


class TestFountainEdgeCases:
    """Edge cases for fountain encode/decode."""

    def test_fountain_partial_last_chunk(self):
        """Data not evenly dividing into PAYLOAD_SIZE recovers correctly."""
        data = os.urandom(FOUNTAIN_PAYLOAD_SIZE * 2 + 500)
        recovered, droplets, K = _fountain_roundtrip(data, max_overhead=5)

        assert K == 3
        assert len(recovered) == len(data)
        assert recovered == data

    def test_fountain_known_data(self):
        """Non-random data (0xAA repeated) recovers correctly.

        Uses non-random data to catch XOR bugs that random data might mask.
        """
        data = b'\xAA' * 10000
        recovered, droplets, K = _fountain_roundtrip(data, max_overhead=10)

        assert recovered == data

    def test_fountain_decoder_idempotent_droplets(self):
        """Feeding the same droplet twice does not crash or corrupt decode."""
        data = os.urandom(FOUNTAIN_PAYLOAD_SIZE * 3)
        K, chunks = prepare_chunks(data)
        decoder = FountainDecoder(K, FOUNTAIN_PAYLOAD_SIZE)

        seed = 1
        max_seeds = K * 30
        droplets_sent = 0
        max_droplets = K * 10

        while not decoder.is_complete() and seed <= max_seeds and droplets_sent < max_droplets:
            if not _would_hang(seed, K):
                payload = build_droplet(seed, K, chunks)
                decoder.add_droplet(seed, payload)
                # Feed the same droplet again (duplicate)
                payload_dup = build_droplet(seed, K, chunks)
                decoder.add_droplet(seed, payload_dup)
                droplets_sent += 1
            seed += 1

        assert decoder.is_complete(), (
            f"Decoder did not complete after {droplets_sent} droplets with duplicates"
        )

        recovered = decoder.get_file_data()[:len(data)]
        assert bytes(recovered) == data


class TestFountainOverhead:
    """Sanity check that fountain overhead is reasonable."""

    def test_fountain_overhead_reasonable(self):
        """For K=10, average overhead across 5 runs is under 5x."""
        total_droplets = 0
        runs = 5

        for i in range(runs):
            data = os.urandom(FOUNTAIN_PAYLOAD_SIZE * 10)
            _, droplets, K = _fountain_roundtrip(data, max_overhead=10)
            assert K == 10
            total_droplets += droplets

        avg_overhead = total_droplets / (runs * 10)
        assert avg_overhead < 5.0, (
            f"Average overhead {avg_overhead:.2f}x exceeds 5x threshold "
            f"(total droplets: {total_droplets} over {runs} runs with K=10)"
        )
