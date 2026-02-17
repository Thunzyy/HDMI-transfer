"""Fountain encode/decode round-trip tests.

Tests the fountain coding pipeline (LT codes with SplitMix32 PRNG) without
any hardware. Verifies single-chunk, multi-chunk, partial-chunk, and edge
cases using in-memory encoding and FountainDecoder from the hdmi_exfil package.

IMPORTANT: Fountain mode uses different constants from sequential mode.
All constants are imported from the hdmi_exfil.protocols.fountain module.
"""

import os
import struct
import hashlib

from hdmi_exfil.prng import PRNG, choose_indices
from hdmi_exfil.protocols.degree import robust_soliton_cdf, sample_degree
from hdmi_exfil.protocols.fountain import (
    FountainDecoder, FOUNTAIN_BYTES_PER_FRAME, PAYLOAD_SIZE,
)
from hdmi_exfil.file_handling.metadata import parse_fountain_metadata

# Fountain-specific constants (from package)
FOUNTAIN_HEADER_LEN = 12  # magic(2) + seed(4) + K(2) + crc(4)
FOUNTAIN_PAYLOAD_SIZE = PAYLOAD_SIZE  # 4038


def _choose_indices_set(seed, K):
    """Wrapper that returns a set (not frozenset) for compatibility with tests."""
    return set(choose_indices(seed, K))


def build_droplet(seed, K, chunks):
    """Build a fountain-encoded droplet by XOR-ing selected chunks."""
    indices = _choose_indices_set(seed, K)
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

    Uses the Robust Soliton Distribution (RSD), matching the production
    code in choose_indices and FountainDecoder.add_droplet.
    """
    prng = PRNG(seed)
    cdf = robust_soliton_cdf(K)
    return sample_degree(cdf, prng)


def _would_hang(seed, K):
    """Check if FountainDecoder.add_droplet would infinite-loop for this seed.

    Known bug: production code does not cap degree to K, so when degree > K
    the while loop in add_droplet can never terminate.
    """
    return _compute_degree(seed, K) > K


def _fountain_roundtrip(data, max_overhead=10):
    """Helper: encode data as fountain droplets, decode, return recovered data.

    Now that chooseIndices bug is fixed (degree capped to K), we no longer
    need to skip seeds that would have caused infinite loops.

    Args:
        data: Original bytes to encode.
        max_overhead: Maximum multiplier over K for droplet budget.

    Returns:
        Tuple of (recovered_bytes_trimmed, droplets_used, K).
    """
    K, chunks = prepare_chunks(data)
    decoder = FountainDecoder(K, FOUNTAIN_PAYLOAD_SIZE)

    seed = 1
    max_droplets = K * max_overhead
    droplets_used = 0

    while not decoder.is_complete() and droplets_used < max_droplets:
        payload = build_droplet(seed, K, chunks)
        decoder.add_droplet(seed, payload)
        droplets_used += 1
        seed += 1

    assert decoder.is_complete(), (
        f"Decoder did not complete after {droplets_used} droplets "
        f"(K={K}, recovered {len(decoder.chunks)}/{K} chunks)"
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
        droplets_sent = 0
        max_droplets = K * 10

        while not decoder.is_complete() and droplets_sent < max_droplets:
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
    """Sanity check that fountain overhead is reasonable.

    With RSD + GE (Phase 5), K=10 typically achieves ~1.2x overhead.
    Threshold tightened from 5.0x to 2.0x (still generous for small K).
    For comprehensive overhead benchmarks, see test_fountain_overhead.py.
    """

    def test_fountain_overhead_reasonable(self):
        """For K=10, average overhead across 5 runs is under 2x."""
        total_droplets = 0
        runs = 5

        for i in range(runs):
            data = os.urandom(FOUNTAIN_PAYLOAD_SIZE * 10)
            _, droplets, K = _fountain_roundtrip(data, max_overhead=10)
            assert K == 10
            total_droplets += droplets

        avg_overhead = total_droplets / (runs * 10)
        assert avg_overhead < 2.0, (
            f"Average overhead {avg_overhead:.2f}x exceeds 2.0x threshold "
            f"(total droplets: {total_droplets} over {runs} runs with K=10)"
        )


class TestChooseIndicesBugfix:
    """Tests that the chooseIndices infinite-loop bug is fixed."""

    def test_k1_no_hang(self):
        """K=1 fountain round-trip works (previously could hang)."""
        data = os.urandom(FOUNTAIN_PAYLOAD_SIZE)
        recovered, droplets, K = _fountain_roundtrip(data, max_overhead=5)
        assert K == 1
        assert recovered == data

    def test_k1_decoder_direct(self):
        """FountainDecoder.add_droplet with K=1 completes without hanging."""
        decoder = FountainDecoder(1, FOUNTAIN_PAYLOAD_SIZE)
        # Seed 1 with K=1: degree will be capped to 1
        payload = os.urandom(FOUNTAIN_PAYLOAD_SIZE)
        decoder.add_droplet(1, bytearray(payload))
        assert decoder.is_complete()
        assert bytes(decoder.chunks[0]) == payload


class TestFountainCRC32:
    """Tests for CRC32 integrity in fountain protocol."""

    def test_crc32_known_vector(self):
        """Python zlib.crc32 matches IEEE 802.3 test vector."""
        import zlib
        assert zlib.crc32(b'123456789') & 0xFFFFFFFF == 0xCBF43926


class TestFountainMetadata:
    """Tests for the enhanced fountain metadata format."""

    def test_metadata_roundtrip(self):
        """Metadata (file_size, SHA-256, filename) packs and parses correctly."""
        file_data = os.urandom(5000)
        filename = "test_file.txt"
        sha256_hash = hashlib.sha256(file_data).digest()
        fname_bytes = filename.encode('utf-8')

        # Build metadata in new format
        metadata = struct.pack('>I', len(file_data))       # 4B file_size
        metadata += sha256_hash                             # 32B SHA-256
        metadata += struct.pack('>H', len(fname_bytes))     # 2B name_len
        metadata += fname_bytes                             # NB filename
        full = metadata + file_data                         # content follows

        # Parse it back
        size, sha, name, offset = parse_fountain_metadata(full)
        assert size == len(file_data)
        assert sha == sha256_hash
        assert name == filename
        assert full[offset:offset + size] == file_data

    def test_metadata_sha256_verification(self):
        """SHA-256 from metadata matches hash of extracted file content."""
        file_data = os.urandom(10000)
        sha256_hash = hashlib.sha256(file_data).digest()
        fname = "verify.bin".encode()

        full = struct.pack('>I', len(file_data)) + sha256_hash + \
               struct.pack('>H', len(fname)) + fname + file_data

        size, expected_sha, _, offset = parse_fountain_metadata(full)
        actual_sha = hashlib.sha256(full[offset:offset + size]).digest()
        assert actual_sha == expected_sha

    def test_metadata_sha256_detects_corruption(self):
        """Corrupted content produces SHA-256 mismatch."""
        file_data = os.urandom(1000)
        sha256_hash = hashlib.sha256(file_data).digest()
        fname = "corrupt.bin".encode()

        # Build valid metadata
        full = bytearray(struct.pack('>I', len(file_data)) + sha256_hash +
                         struct.pack('>H', len(fname)) + fname + file_data)

        # Corrupt one byte of file content
        content_offset = 4 + 32 + 2 + len(fname)
        full[content_offset] ^= 0xFF

        size, expected_sha, _, offset = parse_fountain_metadata(bytes(full))
        actual_sha = hashlib.sha256(full[offset:offset + size]).digest()
        assert actual_sha != expected_sha, "SHA-256 should detect corruption"

    def test_metadata_with_fountain_roundtrip(self):
        """Full fountain encode/decode with metadata prefix recovers file and verifies SHA-256."""
        # Simulate wrapping: metadata + file content -> fountain encode -> decode -> unwrap
        file_data = os.urandom(2000)
        filename = "fountain_meta_test.bin"
        sha256_hash = hashlib.sha256(file_data).digest()
        fname_bytes = filename.encode('utf-8')

        wrapped = struct.pack('>I', len(file_data)) + sha256_hash + \
                  struct.pack('>H', len(fname_bytes)) + fname_bytes + file_data

        # Fountain encode/decode the wrapped data
        K, chunks = prepare_chunks(wrapped)
        decoder = FountainDecoder(K, FOUNTAIN_PAYLOAD_SIZE)

        seed = 1
        max_droplets = K * 10
        while not decoder.is_complete() and seed <= max_droplets:
            payload = build_droplet(seed, K, chunks)
            decoder.add_droplet(seed, payload)
            seed += 1

        assert decoder.is_complete()

        # Reassemble and parse metadata
        recovered = decoder.get_file_data()
        size, expected_sha, name, offset = parse_fountain_metadata(recovered)

        assert name == filename
        assert size == len(file_data)

        # Extract content and verify SHA-256
        content = bytes(recovered[offset:offset + size])
        actual_sha = hashlib.sha256(content).digest()
        assert actual_sha == expected_sha
        assert content == file_data

    def test_metadata_parse_failure_on_garbage(self):
        """parse_fountain_metadata returns None tuple on garbage input."""
        size, sha, name, offset = parse_fountain_metadata(b'\x00' * 10)
        assert size is None or name is None  # Too short
