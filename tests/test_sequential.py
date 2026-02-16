"""In-memory sequential encode/decode round-trip tests.

Tests the sequential encoding pipeline (3-bit per block, RGB channels)
without any hardware. Verifies single-frame, multi-frame, edge cases,
magic number rejection, and CRC32 integrity checking.
"""

import os
import struct
import zlib

import numpy as np

from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import (BYTES_PER_FRAME, BLOCKS_PER_FRAME, ROWS, COLS,
                    SEQ_MAGIC, SEQ_HEADER_FMT, SEQ_HEADER_PRE_CRC,
                    HEADER_SIZE, FRAME_TYPE_DATA, FRAME_TYPE_START,
                    FRAME_TYPE_END)


def _encode_decode(data, frame_index, total_frames):
    """Helper: encode data into a frame, sample it, and decode it."""
    frame = encode_frame(data, frame_index, total_frames)
    sampled = sample_frame(frame)
    return decode_frame(sampled)


class TestSingleFrameRoundtrip:
    """Single-frame encode/decode round-trip tests."""

    def test_single_frame_roundtrip_full(self):
        """Full BYTES_PER_FRAME of known data survives encode/decode."""
        data = b'\x42' * BYTES_PER_FRAME
        idx, total, decoded, length = _encode_decode(data, 0, 1)

        assert idx == 0
        assert total == 1
        assert length == BYTES_PER_FRAME
        assert decoded == data

    def test_single_frame_roundtrip_partial(self):
        """Data smaller than BYTES_PER_FRAME survives encode/decode."""
        original = b'\xAB' * 100
        idx, total, decoded, length = _encode_decode(original, 0, 1)

        assert idx == 0
        assert total == 1
        assert length == 100
        assert decoded[:100] == original


class TestMultiFrameRoundtrip:
    """Multi-frame encode/decode round-trip tests."""

    def test_multi_frame_roundtrip(self):
        """Data spanning 3 frames reassembles correctly."""
        # Create data that spans 3 frames (slightly less than 3 full frames)
        data_size = BYTES_PER_FRAME * 3 - 500
        original_data = os.urandom(data_size)
        total_frames = 3

        reassembled = bytearray()

        for i in range(total_frames):
            start = i * BYTES_PER_FRAME
            end = min((i + 1) * BYTES_PER_FRAME, data_size)
            chunk = original_data[start:end]

            idx, total, decoded, length = _encode_decode(chunk, i, total_frames)

            assert idx == i
            assert total == total_frames
            assert length == len(chunk)
            reassembled.extend(decoded[:length])

        assert reassembled == bytearray(original_data)


class TestMetadataPreservation:
    """Tests that frame index and total_frames survive encode/decode."""

    def test_frame_index_preserved(self):
        """Encoding 5 frames with indices 0-4, each decoded index matches."""
        data = b'\x42' * 100
        total = 5

        for expected_idx in range(total):
            idx, decoded_total, _, _ = _encode_decode(data, expected_idx, total)
            assert idx == expected_idx, (
                f"Frame index mismatch: expected {expected_idx}, got {idx}"
            )

    def test_total_frames_preserved(self):
        """total_frames=42 survives encode/decode."""
        data = b'\x42' * 100
        _, decoded_total, _, _ = _encode_decode(data, 0, 42)
        assert decoded_total == 42


class TestEdgeCases:
    """Edge-case tests for encode/decode pipeline."""

    def test_empty_data_handling(self):
        """Encoding empty bytes returns (None, None, None, None).

        decode_frame rejects data_len == 0 via its sanity check.
        """
        idx, total, decoded, length = _encode_decode(b'', 0, 1)

        assert idx is None
        assert total is None
        assert decoded is None
        assert length is None

    def test_all_zeros_data(self):
        """BYTES_PER_FRAME of 0x00 survives encode/decode."""
        data = b'\x00' * BYTES_PER_FRAME
        idx, total, decoded, length = _encode_decode(data, 0, 1)

        assert idx == 0
        assert total == 1
        assert length == BYTES_PER_FRAME
        assert decoded == data

    def test_all_ones_data(self):
        """BYTES_PER_FRAME of 0xFF survives encode/decode."""
        data = b'\xFF' * BYTES_PER_FRAME
        idx, total, decoded, length = _encode_decode(data, 0, 1)

        assert idx == 0
        assert total == 1
        assert length == BYTES_PER_FRAME
        assert decoded == data


# ---------------------------------------------------------------------------
# Protocol header tests (Phase 2)
# ---------------------------------------------------------------------------

def _bytes_to_grid(frame_bytes):
    """Convert raw frame bytes into the sampled grid format decode_frame expects.

    Pads to full frame capacity, converts to bits, reshapes to (ROWS, COLS, 3).
    """
    total_bits = BLOCKS_PER_FRAME * 3
    total_bytes_needed = (total_bits + 7) // 8
    padded = frame_bytes + b'\x00' * (total_bytes_needed - len(frame_bytes))
    byte_arr = np.frombuffer(padded, dtype=np.uint8)
    bits = np.unpackbits(byte_arr)[:total_bits]
    pixel_bits = bits.reshape((-1, 3)) * 255
    grid = pixel_bits.reshape((ROWS, COLS, 3)).astype(np.uint8)
    return grid


class TestMagicNumberRejection:
    """Tests that frames without valid magic number are rejected."""

    def test_valid_magic_accepted(self):
        """Frame with correct magic 0xDA7A is accepted."""
        data = b'\x42' * 100
        idx, total, decoded, length = _encode_decode(data, 0, 1)
        assert idx == 0
        assert length == 100

    def test_noise_frame_rejected(self):
        """Random noise frame (no magic) returns None."""
        # Create a random grid that won't have the magic number
        rng = np.random.default_rng(42)
        noise_grid = rng.integers(0, 256, (ROWS, COLS, 3), dtype=np.uint8)
        idx, total, data, length = decode_frame(noise_grid)
        assert idx is None
        assert total is None

    def test_wrong_magic_rejected(self):
        """Frame with wrong magic number is rejected by decode_frame."""
        wrong_magic = 0xBEEF
        header = struct.pack(SEQ_HEADER_FMT, wrong_magic, FRAME_TYPE_DATA, 0, 1, 50)
        payload = b'\x42' * 50
        crc = zlib.crc32(header + payload) & 0xFFFFFFFF
        frame_bytes = header + struct.pack('>I', crc) + payload
        grid = _bytes_to_grid(frame_bytes)
        idx, total, data, length = decode_frame(grid)
        assert idx is None, "Frame with wrong magic should be rejected"

    def test_fountain_magic_rejected_by_sequential_decoder(self):
        """Frame with fountain magic (0xF0C0) is rejected by sequential decode."""
        from common import FOUNTAIN_MAGIC
        header = struct.pack(SEQ_HEADER_FMT, FOUNTAIN_MAGIC, FRAME_TYPE_DATA, 0, 1, 50)
        payload = b'\x42' * 50
        crc = zlib.crc32(header + payload) & 0xFFFFFFFF
        frame_bytes = header + struct.pack('>I', crc) + payload
        grid = _bytes_to_grid(frame_bytes)
        idx, total, data, length = decode_frame(grid)
        assert idx is None, "Fountain magic should be rejected by sequential decoder"


class TestCRC32Integrity:
    """Tests that CRC32 detects frame corruption."""

    def test_valid_crc_accepted(self):
        """Unmodified frame passes CRC check."""
        data = b'\xAB' * 500
        idx, total, decoded, length = _encode_decode(data, 0, 1)
        assert idx == 0
        assert decoded[:length] == data

    def test_corrupted_payload_detected(self):
        """Flipping payload bits causes CRC mismatch -> rejection."""
        # Build a valid frame manually, then corrupt the payload
        payload = b'\x42' * 1000
        header = struct.pack(SEQ_HEADER_FMT, SEQ_MAGIC, FRAME_TYPE_DATA, 0, 1, len(payload))
        crc = zlib.crc32(header + payload) & 0xFFFFFFFF
        frame_bytes = header + struct.pack('>I', crc) + payload

        # Corrupt one payload byte (flip all bits in byte after header)
        corrupted = bytearray(frame_bytes)
        corrupted[HEADER_SIZE + 10] ^= 0xFF
        corrupted = bytes(corrupted)

        grid = _bytes_to_grid(corrupted)
        idx, total, data, length = decode_frame(grid)
        assert idx is None, "Corrupted payload should fail CRC check"

    def test_corrupted_header_detected(self):
        """Flipping a header bit (after magic) causes CRC mismatch."""
        payload = b'\x42' * 100
        header = struct.pack(SEQ_HEADER_FMT, SEQ_MAGIC, FRAME_TYPE_DATA, 0, 1, len(payload))
        crc = zlib.crc32(header + payload) & 0xFFFFFFFF
        frame_bytes = header + struct.pack('>I', crc) + payload

        # Corrupt a byte in the frame_index field (bytes 3-6 of header)
        corrupted = bytearray(frame_bytes)
        corrupted[4] ^= 0x01  # Flip one bit in frame_index
        corrupted = bytes(corrupted)

        grid = _bytes_to_grid(corrupted)
        idx, total, data, length = decode_frame(grid)
        assert idx is None, "Corrupted header should fail CRC check"

    def test_crc32_known_vector(self):
        """Python zlib.crc32 produces correct IEEE 802.3 test vector."""
        assert zlib.crc32(b'') & 0xFFFFFFFF == 0x00000000
        assert zlib.crc32(b'123456789') & 0xFFFFFFFF == 0xCBF43926

    def test_frame_type_preserved_in_roundtrip(self):
        """Frame with non-default frame_type still round-trips correctly.

        The frame_type is not returned by decode_frame (callers don't need it
        yet), but it must not break the CRC or header parsing.
        """
        data = b'\x42' * 100
        frame = encode_frame(data, 0, 1, frame_type=FRAME_TYPE_START)
        sampled = sample_frame(frame)
        idx, total, decoded, length = decode_frame(sampled)
        assert idx == 0
        assert total == 1
        assert length == 100
        assert decoded[:length] == data
