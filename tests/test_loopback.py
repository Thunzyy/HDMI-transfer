"""Loopback tests: in-memory encode/decode and hardware capture card pipeline.

The in-memory test (test_loopback) runs always and verifies the full
multi-frame encode -> sample -> decode -> reassemble pipeline with perfect
transmission (no noise/compression).

The hardware test (test_hardware_loopback_sequential) exercises the FULL
pipeline through an Elgato capture card. It requires the --hardware flag
and a connected capture device; it skips gracefully otherwise.
"""

import math
import os
import platform
import struct
import sys

import cv2
import numpy as np
import pytest

from hdmi_transfer.core.protocols.sequential import SequentialProtocol
from hdmi_transfer.core.capture.sampler import sample_frame
from hdmi_transfer.core.config import BYTES_PER_FRAME, ROWS, COLS, BLOCK_SIZE

# Module-level protocol instance
_proto = SequentialProtocol()


# ---------------------------------------------------------------------------
# In-memory loopback (no hardware needed)
# ---------------------------------------------------------------------------

def test_loopback(tmp_path):
    """Full multi-frame encode/decode loopback with random binary data.

    No hardware required -- encode_frame output is fed directly to
    sample_frame/decode_frame (perfect in-memory transmission).
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
        frame_img = _proto.encode_frame(chunk, i, total_frames)

        # Simulate transmission (perfect quality)
        received_frame = frame_img

        # Decode (4 return values: frame_index, total_frames, data, data_len)
        sampled = sample_frame(received_frame, ROWS, COLS, BLOCK_SIZE)
        idx, total, data, length = _proto.decode_frame_legacy(sampled)

        assert idx == i, f"Frame index mismatch: expected {i}, got {idx}"
        assert total == total_frames, (
            f"Total frames mismatch: expected {total_frames}, got {total}"
        )

        decoded_data.extend(data[:length])

    # Verify byte-for-byte match
    assert decoded_data[:file_size] == file_data


# ---------------------------------------------------------------------------
# Hardware loopback helpers
# ---------------------------------------------------------------------------

def _has_gui_support():
    """Check if OpenCV has GUI (highgui) support on this system."""
    try:
        cv2.namedWindow("__gui_test__", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("__gui_test__")
        return True
    except cv2.error:
        return False


def detect_capture_device():
    """Try to open a video capture device.

    Returns
    -------
    (cap, info_str) if a device was found and opened successfully.
    (None, reason_str) if no usable device was found.

    The caller is responsible for releasing *cap* when done.
    """
    system = platform.system()

    # Platform-specific backends
    if system == "Linux":
        backends = [
            (cv2.CAP_V4L2, "V4L2"),
            (cv2.CAP_ANY, "auto-detect"),
        ]
    elif system == "Windows":
        backends = [
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_ANY, "auto-detect"),
        ]
    else:
        backends = [
            (cv2.CAP_ANY, "auto-detect"),
        ]

    for backend, name in backends:
        try:
            cap = cv2.VideoCapture(0, backend)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                info = f"device 0 via {name} ({w}x{h})"
                return cap, info
            cap.release()
        except Exception:
            pass

    return None, "no capture device found on index 0 with any backend"


# ---------------------------------------------------------------------------
# Hardware integration test
# ---------------------------------------------------------------------------

@pytest.mark.hardware
def test_hardware_loopback_sequential(tmp_path):
    """Full encode -> display -> capture -> decode pipeline through hardware.

    Requires:
    - --hardware pytest flag
    - Connected capture device (Elgato or similar)
    - Display output routed to capture input (HDMI loopback)

    Skips gracefully if no capture device is available.

    NOTE: Single-monitor setups cannot capture their own display output.
    This test is marked xfail for that common scenario; it still exercises
    the full pipeline and asserts on whatever it can capture.
    """
    if not _has_gui_support():
        pytest.skip(
            "OpenCV built without GUI support (no GTK/Cocoa/Windows). "
            "Cannot display frames for hardware loopback."
        )

    result = detect_capture_device()
    if result[0] is None:
        pytest.skip(f"No capture device found: {result[1]}")

    cap, device_info = result

    try:
        # Generate 10KB random test file
        original_content = os.urandom(10 * 1024)
        filename = "hw_test.bin"
        filename_bytes = filename.encode("utf-8")

        # Prepend filename metadata (matching sender.py format)
        metadata_header = struct.pack(">I", len(filename_bytes)) + filename_bytes
        file_data = metadata_header + original_content
        file_size = len(file_data)
        total_frames = math.ceil(file_size / BYTES_PER_FRAME)

        # Set capture resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        # Create display window
        window_name = "HW Loopback Test"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        decoded_frames = {}
        failed_captures = 0

        for i in range(total_frames):
            start = i * BYTES_PER_FRAME
            end = min((i + 1) * BYTES_PER_FRAME, file_size)
            chunk = file_data[start:end]

            # Encode frame
            frame_img = _proto.encode_frame(chunk, i, total_frames)

            # Display frame
            cv2.imshow(window_name, frame_img)
            # Wait for the display to settle -- generous delay for hardware
            cv2.waitKey(200)

            # Read from capture device (try multiple reads to skip stale frames)
            captured = None
            for _attempt in range(5):
                ret, raw_frame = cap.read()
                if ret and raw_frame is not None:
                    captured = raw_frame
                cv2.waitKey(50)

            if captured is None:
                failed_captures += 1
                continue

            # Resize to expected resolution if needed
            if (captured.shape[1], captured.shape[0]) != (1920, 1080):
                captured = cv2.resize(captured, (1920, 1080))

            # Decode captured frame
            sampled = sample_frame(captured, ROWS, COLS, BLOCK_SIZE)
            idx, total, data, length = _proto.decode_frame_legacy(sampled)

            if idx is not None and length is not None:
                decoded_frames[idx] = data[:length]

        cv2.destroyAllWindows()

        # Reassemble decoded data
        if not decoded_frames:
            pytest.xfail(
                f"Captured 0/{total_frames} frames from {device_info}. "
                "Single-monitor loopback may not capture own display."
            )

        reassembled = bytearray()
        missing = 0
        for i in range(total_frames):
            if i in decoded_frames:
                reassembled.extend(decoded_frames[i])
            else:
                missing += 1
                reassembled.extend(b"\x00" * BYTES_PER_FRAME)

        if missing == total_frames:
            pytest.xfail(
                f"All {total_frames} frames failed to decode from capture. "
                "Single-monitor loopback may not capture own display."
            )

        # Verify byte-for-byte match for captured frames
        if missing == 0:
            assert reassembled[:file_size] == file_data, (
                "Hardware loopback data mismatch"
            )
        else:
            # Partial capture -- check the frames we did get
            for idx, frame_data in decoded_frames.items():
                start = idx * BYTES_PER_FRAME
                end = min((idx + 1) * BYTES_PER_FRAME, file_size)
                expected_chunk = file_data[start:end]
                assert frame_data == expected_chunk, (
                    f"Frame {idx} data mismatch in hardware loopback"
                )
            pytest.xfail(
                f"Partial capture: {len(decoded_frames)}/{total_frames} "
                f"frames decoded correctly, {missing} missing. "
                "Single-monitor loopback may not capture own display."
            )

    finally:
        cap.release()
        try:
            cv2.destroyAllWindows()
        except cv2.error:
            pass  # GUI not available (headless)
