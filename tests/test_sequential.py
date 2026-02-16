"""In-memory sequential encode/decode round-trip tests.

Tests the sequential encoding pipeline (3-bit per block, RGB channels)
without any hardware. Verifies single-frame, multi-frame, and edge cases.
"""

import os
from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import BYTES_PER_FRAME


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
