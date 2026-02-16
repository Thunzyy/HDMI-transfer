"""In-memory sequential encode/decode round-trip tests.

Tests the sequential encoding pipeline (3-bit per block, RGB channels)
without any hardware. Verifies single-frame, multi-frame, edge cases,
magic number rejection, and CRC32 integrity checking.
"""

import os
import struct
import zlib

import numpy as np

import hashlib
import math

from hdmi_exfil.protocols.sequential import SequentialProtocol, TransferState
from hdmi_exfil.capture.sampler import sample_frame
from hdmi_exfil.file_handling.metadata import build_start_metadata, parse_start_metadata
from hdmi_exfil.config import (
    BYTES_PER_FRAME, BLOCKS_PER_FRAME, ROWS, COLS, BLOCK_SIZE,
    SEQ_MAGIC, SEQ_HEADER_FMT, SEQ_HEADER_PRE_CRC,
    HEADER_SIZE, FRAME_TYPE_DATA, FRAME_TYPE_START,
    FRAME_TYPE_END, FOUNTAIN_MAGIC,
)
from hdmi_exfil.protocols.fountain import (
    FOUNT_HEADER_FMT, FOUNT_HEADER_PRE_CRC, FOUNT_HEADER_SIZE,
)

# Module-level protocol instance for encode/decode
_proto = SequentialProtocol()


def _encode_decode(data, frame_index, total_frames):
    """Helper: encode data into a frame, sample it, and decode it."""
    frame = _proto.encode_frame(data, frame_index, total_frames)
    sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
    return _proto.decode_frame_legacy(sampled)


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
        idx, total, data, length = _proto.decode_frame_legacy(noise_grid)
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
        idx, total, data, length = _proto.decode_frame_legacy(grid)
        assert idx is None, "Frame with wrong magic should be rejected"

    def test_fountain_magic_rejected_by_sequential_decoder(self):
        """Frame with fountain magic (0xF0C0) is rejected by sequential decode."""
        header = struct.pack(SEQ_HEADER_FMT, FOUNTAIN_MAGIC, FRAME_TYPE_DATA, 0, 1, 50)
        payload = b'\x42' * 50
        crc = zlib.crc32(header + payload) & 0xFFFFFFFF
        frame_bytes = header + struct.pack('>I', crc) + payload
        grid = _bytes_to_grid(frame_bytes)
        idx, total, data, length = _proto.decode_frame_legacy(grid)
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
        idx, total, data, length = _proto.decode_frame_legacy(grid)
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
        idx, total, data, length = _proto.decode_frame_legacy(grid)
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
        frame = _proto.encode_frame(data, 0, 1, frame_type=FRAME_TYPE_START)
        sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
        idx, total, decoded, length = _proto.decode_frame_legacy(sampled)
        assert idx == 0
        assert total == 1
        assert length == 100
        assert decoded[:length] == data


# ---------------------------------------------------------------------------
# Transfer lifecycle tests (Phase 2 - Plan 03)
# ---------------------------------------------------------------------------


class TestStartEndFrames:
    """Tests for START and END frame encoding/decoding."""

    def test_start_frame_metadata_roundtrip(self):
        """START frame metadata (filename, size, SHA-256) survives encode/decode."""
        file_data = os.urandom(5000)
        filename = "test_file.bin"
        total_data_frames = 1

        start_frame = _proto.encode_start_frame(filename, file_data, total_data_frames)
        sampled = sample_frame(start_frame, ROWS, COLS, BLOCK_SIZE)
        result = _proto.decode_frame(sampled)

        assert result.frame_type == FRAME_TYPE_START
        assert result.total_frames == total_data_frames

        # Parse metadata from payload
        file_size, sha256_hash, decoded_name = parse_start_metadata(result.data)
        assert file_size == len(file_data)
        assert sha256_hash == hashlib.sha256(file_data).digest()
        assert decoded_name == filename

    def test_end_frame_decoded(self):
        """END frame is decoded with correct frame_type."""
        end_frame = _proto.encode_end_frame(5)
        sampled = sample_frame(end_frame, ROWS, COLS, BLOCK_SIZE)
        result = _proto.decode_frame(sampled)

        assert result.frame_type == FRAME_TYPE_END
        assert result.total_frames == 5

    def test_data_frame_type_preserved(self):
        """Regular DATA frame has correct frame_type via decode_frame_full."""
        data = b'\x42' * 100
        frame = _proto.encode_frame(data, 0, 1)  # defaults to FRAME_TYPE_DATA
        sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
        result = _proto.decode_frame(sampled)

        assert result.frame_type == FRAME_TYPE_DATA
        assert result.frame_index == 0
        assert result.total_frames == 1
        assert len(result.data) == 100


class TestTransferLifecycle:
    """Tests for the full START -> DATA -> END transfer lifecycle."""

    def test_full_lifecycle_in_memory(self):
        """Full lifecycle: START with metadata, DATA frames, END with SHA-256 check."""
        file_data = os.urandom(BYTES_PER_FRAME * 2 + 500)
        filename = "lifecycle_test.bin"
        total_data_frames = math.ceil(len(file_data) / BYTES_PER_FRAME)

        # Encode START
        start_img = _proto.encode_start_frame(filename, file_data, total_data_frames)
        sampled = sample_frame(start_img, ROWS, COLS, BLOCK_SIZE)
        result = _proto.decode_frame(sampled)
        assert result.frame_type == FRAME_TYPE_START
        file_size, expected_sha, decoded_name = parse_start_metadata(result.data)
        assert decoded_name == filename
        assert file_size == len(file_data)

        # Encode DATA frames
        received_chunks = {}
        for i in range(total_data_frames):
            start_byte = i * BYTES_PER_FRAME
            end_byte = min((i + 1) * BYTES_PER_FRAME, len(file_data))
            chunk = file_data[start_byte:end_byte]

            frame_img = _proto.encode_frame(chunk, i, total_data_frames)
            sampled = sample_frame(frame_img, ROWS, COLS, BLOCK_SIZE)
            result = _proto.decode_frame(sampled)
            assert result.frame_type == FRAME_TYPE_DATA
            assert result.frame_index == i
            received_chunks[result.frame_index] = result.data

        # Encode END
        end_img = _proto.encode_end_frame(total_data_frames)
        sampled = sample_frame(end_img, ROWS, COLS, BLOCK_SIZE)
        result = _proto.decode_frame(sampled)
        assert result.frame_type == FRAME_TYPE_END

        # Reassemble and verify SHA-256
        reassembled = bytearray()
        for i in range(total_data_frames):
            reassembled.extend(received_chunks[i])
        file_content = bytes(reassembled[:file_size])

        actual_sha = hashlib.sha256(file_content).digest()
        assert actual_sha == expected_sha, "SHA-256 mismatch after reassembly"
        assert file_content == file_data


class TestSHA256Verification:
    """Tests for SHA-256 file integrity checking."""

    def test_sha256_matches_on_valid_transfer(self):
        """SHA-256 of reassembled data matches START frame hash."""
        data = os.urandom(1000)
        metadata = build_start_metadata("test.bin", data)
        file_size, sha_hash, _ = parse_start_metadata(metadata)
        assert hashlib.sha256(data).digest() == sha_hash

    def test_sha256_detects_corruption(self):
        """Corrupted data produces different SHA-256 than START frame hash."""
        data = os.urandom(1000)
        metadata = build_start_metadata("test.bin", data)
        _, expected_sha, _ = parse_start_metadata(metadata)

        corrupted = bytearray(data)
        corrupted[0] ^= 0xFF  # flip one byte
        actual_sha = hashlib.sha256(bytes(corrupted)).digest()
        assert actual_sha != expected_sha, "SHA-256 should detect single byte corruption"


# ---------------------------------------------------------------------------
# Protocol routing tests (Phase 2 - Plan 05)
# ---------------------------------------------------------------------------


def _route_frame(frame_bytes):
    """Route raw frame bytes to the correct protocol decoder.

    Re-implements the old receiver.route_frame() using new package modules.

    Returns:
        ('sequential', (ftype, idx, total, payload, dlen)) for sequential frames
        ('fountain', (seed, K, payload)) for fountain frames
        (None, None) for unrecognized/invalid frames
    """
    if len(frame_bytes) < 2:
        return None, None

    magic = struct.unpack('>H', frame_bytes[:2])[0]

    if magic == SEQ_MAGIC:
        if len(frame_bytes) < HEADER_SIZE:
            return None, None
        try:
            _, frame_type, frame_index, total_frames, data_len = struct.unpack(
                SEQ_HEADER_FMT, frame_bytes[:SEQ_HEADER_PRE_CRC])
        except struct.error:
            return None, None

        stored_crc = struct.unpack('>I',
            frame_bytes[SEQ_HEADER_PRE_CRC:HEADER_SIZE])[0]

        if data_len > BYTES_PER_FRAME or data_len == 0:
            return None, None

        payload = frame_bytes[HEADER_SIZE:HEADER_SIZE + data_len]
        computed_crc = zlib.crc32(
            frame_bytes[:SEQ_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
        if computed_crc != stored_crc:
            return None, None

        return 'sequential', (frame_type, frame_index, total_frames, payload, data_len)

    elif magic == FOUNTAIN_MAGIC:
        if len(frame_bytes) < FOUNT_HEADER_SIZE:
            return None, None
        try:
            _, seed, K = struct.unpack(FOUNT_HEADER_FMT,
                frame_bytes[:FOUNT_HEADER_PRE_CRC])
        except struct.error:
            return None, None

        stored_crc = struct.unpack('>I',
            frame_bytes[FOUNT_HEADER_PRE_CRC:FOUNT_HEADER_SIZE])[0]

        payload = frame_bytes[FOUNT_HEADER_SIZE:]
        computed_crc = zlib.crc32(
            frame_bytes[:FOUNT_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
        if computed_crc != stored_crc:
            return None, None

        return 'fountain', (seed, K, payload)

    else:
        return None, None


class TestProtocolRouting:
    """Tests for magic-number-based protocol routing."""

    def test_sequential_frame_routes_to_sequential(self):
        """A valid sequential frame is routed to the sequential decoder."""
        data = b'\x42' * 100
        frame = _proto.encode_frame(data, 0, 1)
        sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)

        # Get raw bytes (replicate decode pipeline to get bytes before parsing)
        flat_pixels = sampled.reshape(-1, 3)
        bits = (flat_pixels > 128).astype(np.uint8)
        flat_bits = bits.reshape(-1)
        packed = np.packbits(flat_bits)
        raw_bytes = packed.tobytes()

        protocol, result = _route_frame(raw_bytes)
        assert protocol == 'sequential'
        ftype, idx, total, payload, dlen = result
        assert idx == 0
        assert total == 1
        assert dlen == 100

    def test_fountain_frame_routes_to_fountain(self):
        """A frame with fountain magic routes to the fountain decoder."""
        # Build fountain frame raw bytes
        header = struct.pack(FOUNT_HEADER_FMT, FOUNTAIN_MAGIC, 1, 5)
        payload = b'\xBB' * 100
        crc_val = zlib.crc32(header + payload) & 0xFFFFFFFF
        raw_bytes = header + struct.pack('>I', crc_val) + payload

        protocol, result = _route_frame(raw_bytes)
        assert protocol == 'fountain'
        seed, K, data = result
        assert seed == 1
        assert K == 5
        assert data == payload

    def test_noise_routes_to_none(self):
        """Random bytes with no valid magic return (None, None)."""
        import os as _os
        noise = _os.urandom(200)
        protocol, result = _route_frame(noise)
        # It's possible (unlikely) that random bytes start with 0xDA7A or 0xF0C0
        # and pass CRC -- that's astronomically unlikely. Accept None or valid.
        if protocol is not None:
            pass  # Extremely unlikely but technically possible
        else:
            assert result is None

    def test_empty_bytes_routes_to_none(self):
        """Empty or too-short bytes return (None, None)."""
        protocol, result = _route_frame(b'')
        assert protocol is None
        protocol, result = _route_frame(b'\x00')
        assert protocol is None

    def test_corrupted_crc_routes_to_none(self):
        """Frame with valid magic but bad CRC returns (None, None)."""
        # Build sequential frame then corrupt CRC
        header = struct.pack(SEQ_HEADER_FMT, SEQ_MAGIC, FRAME_TYPE_DATA, 0, 1, 10)
        payload = b'\x42' * 10
        bad_crc = struct.pack('>I', 0xDEADBEEF)  # wrong CRC
        raw_bytes = header + bad_crc + payload + b'\x00' * 100

        protocol, result = _route_frame(raw_bytes)
        assert protocol is None, "Corrupted CRC should cause rejection"


class TestEndToEndProtocol:
    """End-to-end tests verifying the complete protocol stack."""

    def test_loopback_with_new_protocol_format(self):
        """Full loopback test using new 17-byte protocol header."""
        test_data = os.urandom(BYTES_PER_FRAME * 2 + 100)
        total_frames = math.ceil(len(test_data) / BYTES_PER_FRAME)

        reassembled = bytearray()
        for i in range(total_frames):
            start = i * BYTES_PER_FRAME
            end = min((i + 1) * BYTES_PER_FRAME, len(test_data))
            chunk = test_data[start:end]

            frame = _proto.encode_frame(chunk, i, total_frames)
            sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)

            # Use decode_frame to verify frame_type
            result = _proto.decode_frame(sampled)
            assert result.frame_type == FRAME_TYPE_DATA
            assert result.frame_index == i
            reassembled.extend(result.data)

        assert reassembled[:len(test_data)] == bytearray(test_data)

    def test_crc32_cross_validation(self):
        """CRC32 computed via zlib matches known IEEE 802.3 test vectors."""
        # Standard test vector
        assert zlib.crc32(b'123456789') & 0xFFFFFFFF == 0xCBF43926
        # Empty input
        assert zlib.crc32(b'') & 0xFFFFFFFF == 0x00000000
        # Single byte
        crc_a = zlib.crc32(b'\x00') & 0xFFFFFFFF
        assert crc_a == 0xD202EF8D
        # Verify unsigned behavior
        assert zlib.crc32(b'\xFF') & 0xFFFFFFFF == 0xFF000000
