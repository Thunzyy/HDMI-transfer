"""CLI entry point for ``hdmi-recv`` -- drives file reception over HDMI.

Orchestrates video capture, frame sampling, protocol decoding, and file
saving.  Contains no decode logic; it is a thin wiring layer over the
``hdmi_exfil`` package modules.

Usage::

    hdmi-recv 0 --mode auto --output received_files
    hdmi-recv recording.mp4 --mode fountain
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

from hdmi_exfil.capture.sampler import sample_frame
from hdmi_exfil.capture.source import CaptureSource
from hdmi_exfil.config import (
    BLOCK_SIZE,
    BYTES_PER_FRAME,
    COLS,
    FRAME_TYPE_DATA,
    FRAME_TYPE_END,
    FRAME_TYPE_START,
    HEIGHT,
    ROWS,
    WIDTH,
)
from hdmi_exfil.file_handling.metadata import (
    parse_fountain_metadata,
    parse_start_metadata,
)
from hdmi_exfil.file_handling.writer import verify_integrity, write_output
from hdmi_exfil.protocols import get_protocol
from hdmi_exfil.protocols.fountain import FountainDecoder
from hdmi_exfil.protocols.sequential import TransferState


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hdmi-recv",
        description="HDMI Exfiltration Receiver -- capture and decode HDMI frames",
    )
    parser.add_argument(
        "source",
        help="Video source (camera index e.g. '0' or file path)",
    )
    parser.add_argument(
        "--output",
        default="received_files",
        help="Directory to save received files (default: received_files)",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "sequential", "fountain"],
        default="auto",
        help="Decoding protocol (default: auto-detect from magic number)",
    )
    return parser


# ------------------------------------------------------------------
# Sequential receive loop
# ------------------------------------------------------------------

def _receive_sequential(
    seq_protocol: object,
    cap: CaptureSource,
    output_dir: str,
) -> None:
    """Run the sequential receive loop (START -> DATA -> END)."""
    state = TransferState.START_PENDING
    expected_sha256: bytes | None = None
    expected_file_size: int | None = None
    expected_filename: str | None = None
    received_chunks: dict[int, bytes] = {}
    total_frames_expected: int | None = None
    start_time: float | None = None

    print("Sequential mode: waiting for START frame...")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            break

        if frame.shape[0] != HEIGHT or frame.shape[1] != WIDTH:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))

        sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
        result = seq_protocol.decode_frame(sampled)

        if result.is_valid:
            ftype = result.frame_type
            data = result.data
            total = result.total_frames
            idx = result.frame_index

            if ftype == FRAME_TYPE_START and state == TransferState.START_PENDING:
                file_size, sha256_hash, filename = parse_start_metadata(data)
                if file_size is not None:
                    expected_sha256 = sha256_hash
                    expected_file_size = file_size
                    expected_filename = filename
                    total_frames_expected = total
                    state = TransferState.RECEIVING
                    start_time = time.time()
                    print(f"START received: '{filename}' ({file_size} bytes)")
                    print(f"Expected SHA-256: {sha256_hash.hex()}")
                    print(f"Expecting {total_frames_expected} DATA frames.")

            elif ftype == FRAME_TYPE_DATA and state == TransferState.RECEIVING:
                if idx not in received_chunks:
                    received_chunks[idx] = data
                    progress = (
                        len(received_chunks) / total_frames_expected
                        if total_frames_expected
                        else 0
                    )
                    sys.stdout.write(
                        f"\rReceiving: {progress:.1%} "
                        f"({len(received_chunks)}/{total_frames_expected})"
                    )
                    sys.stdout.flush()

            elif ftype == FRAME_TYPE_END and state == TransferState.RECEIVING:
                print("\nEND frame received. Reassembling...")
                _finalize_sequential(
                    received_chunks, total_frames_expected,
                    expected_file_size, expected_sha256,
                    expected_filename, output_dir, start_time,
                )
                break

        # Debug window
        debug_frame = frame.copy()
        _draw_grid_overlay(debug_frame, sequential=True)
        cv2.imshow("Receiver View", debug_frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cv2.destroyAllWindows()


def _finalize_sequential(
    received_chunks: dict[int, bytes],
    total_frames: int | None,
    expected_size: int | None,
    expected_sha256: bytes | None,
    expected_filename: str | None,
    output_dir: str,
    start_time: float | None,
) -> None:
    """Reassemble chunks and save file for sequential transfers."""
    if total_frames is None or expected_size is None:
        print("Error: missing transfer metadata.")
        return

    full_data = bytearray()
    missing: list[int] = []
    for i in range(total_frames):
        if i in received_chunks:
            full_data.extend(received_chunks[i])
        else:
            missing.append(i)
            full_data.extend(b"\x00" * BYTES_PER_FRAME)

    if missing:
        print(f"WARNING: Missing frames: {missing}")

    file_content = bytes(full_data[:expected_size])

    if expected_sha256 and not verify_integrity(file_content, expected_sha256):
        print("ERROR: SHA-256 MISMATCH -- file corrupted!")
    else:
        print("SHA-256 verified OK.")

    filename = expected_filename or f"received_{int(time.time())}.bin"
    save_path = write_output(file_content, filename, output_dir)
    print(f"Saved to {save_path}")

    if start_time is not None:
        _print_receive_stats(len(file_content), start_time)


# ------------------------------------------------------------------
# Fountain receive loop
# ------------------------------------------------------------------

def _receive_fountain(
    fount_protocol: object,
    cap: CaptureSource,
    output_dir: str,
) -> None:
    """Run the fountain receive loop (continuous droplets until complete)."""
    decoder: FountainDecoder | None = None
    start_time: float | None = None

    print("Fountain mode: waiting for first valid droplet...")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            break

        if frame.shape[0] != HEIGHT or frame.shape[1] != WIDTH:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))

        sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
        result = fount_protocol.decode_frame(sampled)

        if result.is_valid and result.data is not None:
            seed = result.frame_index  # fountain uses frame_index as seed
            K = result.total_frames
            payload = result.data

            if K is None or K == 0 or K > 60000:
                continue

            # Initialize decoder on first valid packet
            if decoder is None:
                print(f"\nDetected transmission! K={K} chunks.")
                decoder = FountainDecoder(K, len(payload))
                start_time = time.time()

            if decoder.K == K:
                decoder.add_droplet(seed, payload)
                progress = len(decoder.chunks) / K
                sys.stdout.write(
                    f"\rProgress: {progress:.1%} ({len(decoder.chunks)}/{K})"
                )
                sys.stdout.flush()

                if decoder.is_complete():
                    print("\nDownload complete!")
                    _finalize_fountain(decoder, output_dir, start_time)
                    break

        # Debug window
        debug_frame = frame.copy()
        _draw_grid_overlay(debug_frame, sequential=False)
        cv2.imshow("Receiver Fountain", debug_frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cv2.destroyAllWindows()


def _finalize_fountain(
    decoder: FountainDecoder,
    output_dir: str,
    start_time: float | None,
) -> None:
    """Parse metadata, verify integrity, and save file for fountain transfers."""
    full_data = decoder.get_file_data()

    file_size, expected_sha256, filename, content_offset = parse_fountain_metadata(
        full_data,
    )

    if file_size is not None and filename is not None:
        file_content = bytes(full_data[content_offset:content_offset + file_size])

        if expected_sha256 and not verify_integrity(file_content, expected_sha256):
            print("ERROR: SHA-256 MISMATCH -- file corrupted!")
        else:
            print("SHA-256 verified OK.")

        print(f"Detected filename: {filename} ({file_size} bytes)")
    else:
        print("Metadata decode failed. Saving raw payload.")
        file_content = bytes(full_data)
        filename = f"received_{int(time.time())}.bin"

    save_path = write_output(file_content, filename, output_dir)
    print(f"Saved to {save_path}")

    if start_time is not None:
        _print_receive_stats(len(file_content), start_time)


# ------------------------------------------------------------------
# Auto-detect mode
# ------------------------------------------------------------------

def _receive_auto(
    cap: CaptureSource,
    output_dir: str,
) -> None:
    """Auto-detect protocol from magic number and delegate."""
    seq = get_protocol("sequential")
    fount = get_protocol("fountain")

    print("Auto mode: probing frames for protocol magic number...")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            return

        if frame.shape[0] != HEIGHT or frame.shape[1] != WIDTH:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))

        sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)

        # Try sequential first (3-bit encoding)
        seq_result = seq.decode_frame(sampled)
        if seq_result.is_valid:
            print("Detected SEQUENTIAL protocol.")
            # We already consumed one frame; re-enter sequential loop
            # which handles the full lifecycle. The captured frame was
            # processed but the loop will continue reading.
            _receive_sequential(seq, cap, output_dir)
            return

        # Try fountain (1-bit encoding)
        fount_result = fount.decode_frame(sampled)
        if fount_result.is_valid:
            print("Detected FOUNTAIN protocol.")
            _receive_fountain(fount, cap, output_dir)
            return

        # Debug window while probing
        debug_frame = frame.copy()
        cv2.imshow("Receiver (auto-detect)", debug_frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cv2.destroyAllWindows()


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _draw_grid_overlay(frame: np.ndarray, sequential: bool = True) -> None:
    """Draw debug grid overlay on *frame* (in-place)."""
    step = 5 if sequential else 10
    color = (0, 255, 255) if sequential else (0, 0, 255)

    for r in range(0, ROWS, step):
        y = r * BLOCK_SIZE
        cv2.line(frame, (0, y), (WIDTH, y), color, 1)
    for c in range(0, COLS, step):
        x = c * BLOCK_SIZE
        cv2.line(frame, (x, 0), (x, HEIGHT), color, 1)


def _print_receive_stats(total_bytes: int, start_time: float) -> None:
    """Print timing and throughput statistics."""
    duration = time.time() - start_time
    speed = (total_bytes * 8) / duration / 1_000_000 if duration > 0 else 0
    print(f"Time: {duration:.2f}s, Speed: {speed:.2f} Mbps")


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------

def main() -> None:
    """Entry point for ``hdmi-recv`` CLI command."""
    parser = _build_parser()
    args = parser.parse_args()

    # Parse source: numeric string -> camera index
    source: int | str = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    print(f"Opening video source: {source}")

    try:
        cap = CaptureSource(source, WIDTH, HEIGHT, fps=240)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    print(
        f"Camera: {cap.actual_width}x{cap.actual_height} "
        f"@ {cap.actual_fps} FPS"
    )

    with cap:
        if args.mode == "auto":
            _receive_auto(cap, args.output)
        elif args.mode == "sequential":
            seq = get_protocol("sequential")
            _receive_sequential(seq, cap, args.output)
        else:
            fount = get_protocol("fountain")
            _receive_fountain(fount, cap, args.output)


if __name__ == "__main__":
    main()
