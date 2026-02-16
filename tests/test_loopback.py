import os
import pytest
import numpy as np
from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import BYTES_PER_FRAME


@pytest.mark.hardware
def test_loopback(tmp_path):
    """Full encode/decode loopback test with a random binary file.

    Requires Elgato capture card hardware. Skipped by default;
    run with --hardware to enable.
    """
    test_file = tmp_path / "test_data.bin"

    # Generate 100KB random file
    file_data = os.urandom(100 * 1024)
    test_file.write_bytes(file_data)

    # Read file back (mirrors original pattern)
    file_data = test_file.read_bytes()
    file_size = len(file_data)
    total_frames = (file_size + BYTES_PER_FRAME - 1) // BYTES_PER_FRAME

    decoded_data = bytearray()

    for i in range(total_frames):
        start = i * BYTES_PER_FRAME
        end = min((i + 1) * BYTES_PER_FRAME, file_size)
        chunk = file_data[start:end]

        # Encode (3 args: data_chunk, frame_index, total_frames)
        frame_img = encode_frame(chunk, i, total_frames)

        # Simulate transmission (perfect quality)
        received_frame = frame_img

        # Decode (4 return values: frame_index, total_frames, data, data_len)
        sampled = sample_frame(received_frame)
        idx, total, data, length = decode_frame(sampled)

        assert idx == i, f"Frame index mismatch: expected {i}, got {idx}"
        assert total == total_frames, f"Total frames mismatch: expected {total_frames}, got {total}"

        decoded_data.extend(data[:length])

    # Verify byte-for-byte match
    assert decoded_data[:file_size] == file_data
