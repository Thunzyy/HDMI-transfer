"""CLI entry point for ``hdmi-recv`` -- drives file reception over HDMI.

Orchestrates video capture, frame sampling, protocol decoding, and file
saving.  Contains no decode logic; it is a thin wiring layer over the
``hdmi_exfil`` package modules.

Usage::

    hdmi-recv 0 --mode auto --output received_files
    hdmi-recv recording.mp4 --mode fountain
    hdmi-recv 0 --no-threaded --mode sequential
    hdmi-recv 0 --profile quality --mode fountain
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

from hdmi_exfil.core.capture.sampler import sample_frame
from hdmi_exfil.core.cli.progress import ProgressTracker
from hdmi_exfil.receiver.capture.source import CaptureSource
from hdmi_exfil.core.capture.threaded import FPSReporter, ThreadedCapture
from hdmi_exfil.core.config import (
    DEFAULT_PROFILE,
    FRAME_TYPE_DATA,
    FRAME_TYPE_END,
    FRAME_TYPE_START,
    PROFILES,
    ResolutionProfile,
)
from hdmi_exfil.core.file_handling.metadata import (
    parse_fountain_metadata,
    parse_start_metadata,
)
from hdmi_exfil.core.file_handling.writer import verify_integrity, write_output
from hdmi_exfil.core.protocols import get_protocol
from hdmi_exfil.core.protocols.fountain import FountainDecoder
from hdmi_exfil.core.protocols.sequential import TransferState


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
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default=None,
        help="Resolution profile: speed (1080p@240fps), balanced (1080p@60fps), quality (4K@30fps)",
    )
    parser.add_argument(
        "--threaded",
        action="store_true",
        default=True,
        help="Use threaded capture with ring buffer (default: enabled)",
    )
    parser.add_argument(
        "--no-threaded",
        action="store_false",
        dest="threaded",
        help="Disable threaded capture (use blocking reads)",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=16,
        help="Ring buffer size for threaded capture (default: 16 frames)",
    )
    return parser


# ------------------------------------------------------------------
# Sequential receive loop
# ------------------------------------------------------------------

def _receive_sequential(
    seq_protocol: object,
    cap: object,
    output_dir: str,
    profile: ResolutionProfile,
) -> None:
    """Run the sequential receive loop (START -> DATA -> END).

    Accumulates frames across multiple sender passes.  Progress is shown
    on a single ``\\r``-overwritten line that never resets.
    """
    expected_sha256: bytes | None = None
    expected_file_size: int | None = None
    expected_filename: str | None = None
    received_chunks: dict[int, bytes] = {}
    total_frames_expected: int | None = None
    start_time: float = time.time()
    fps_reporter = FPSReporter(report_interval_s=2.0)
    capture_fps_str = ""
    got_start = False
    bytes_received = 0
    pass_count = 0

    print("Sequential mode: capturing frames...")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.001)
            continue

        fps = fps_reporter.tick()
        if fps is not None:
            capture_fps_str = f" | Capture: {fps:.1f} FPS"

        if frame.shape[0] != profile.height or frame.shape[1] != profile.width:
            frame = cv2.resize(frame, (profile.width, profile.height))

        sampled = sample_frame(frame, profile.rows, profile.cols, profile.block_size)
        result = seq_protocol.decode_frame(sampled)

        if result.is_valid:
            ftype = result.frame_type
            data = result.data
            total = result.total_frames
            idx = result.frame_index

            if ftype == FRAME_TYPE_START:
                if not got_start:
                    file_size, sha256_hash, filename = parse_start_metadata(data)
                    if file_size is not None:
                        expected_sha256 = sha256_hash
                        expected_file_size = file_size
                        expected_filename = filename
                        total_frames_expected = total
                        got_start = True
                        print(f"  File: '{filename}' ({file_size} bytes, {total} frames)")

            elif ftype == FRAME_TYPE_DATA:
                # Accept DATA frames even before START
                if total_frames_expected is None and total is not None and total > 0:
                    total_frames_expected = total

                if idx not in received_chunks:
                    received_chunks[idx] = data
                    bytes_received += len(data)

                # Single cumulative progress line (\r only, never \n)
                if total_frames_expected:
                    count = len(received_chunks)
                    pct = count / total_frames_expected
                    elapsed = time.time() - start_time
                    if elapsed > 2.0 and bytes_received > 0:
                        speed = bytes_received / elapsed
                        avg_chunk = bytes_received / count if count else 1
                        remaining = (total_frames_expected - count) * avg_chunk
                        eta = remaining / speed if speed > 0 else float("inf")
                        speed_str = f"{speed / 1024:.1f} KB/s"
                        eta_str = ProgressTracker._format_eta(eta)
                    else:
                        speed_str = "-- KB/s"
                        eta_str = "--:--"
                    pass_str = f" | Pass {pass_count + 1}" if pass_count > 0 else ""
                    sys.stdout.write(
                        f"\rFrames: {count}/{total_frames_expected} "
                        f"({pct:.1%}) | {speed_str} | ETA: {eta_str}"
                        f"{pass_str}{capture_fps_str}    "
                    )
                    sys.stdout.flush()

            elif ftype == FRAME_TYPE_END:
                pass_count += 1
                if total_frames_expected and len(received_chunks) >= total_frames_expected:
                    print("\n\nAll frames received. Reassembling...")
                    _finalize_sequential(
                        received_chunks, total_frames_expected,
                        expected_file_size, expected_sha256,
                        expected_filename, output_dir, start_time,
                        bytes_per_frame=profile.seq_bytes_per_frame,
                    )
                    _print_capture_stats(cap)
                    break
                # Missing frames — progress line keeps updating silently

        # Debug window
        debug_frame = frame.copy()
        _draw_grid_overlay(
            debug_frame, sequential=True,
            rows=profile.rows, cols=profile.cols,
            block_size=profile.block_size,
            width=profile.width, height=profile.height,
        )
        cv2.imshow("Receiver View", debug_frame)
        if cv2.waitKey(1) & 0xFF == 27:
            if received_chunks and total_frames_expected:
                print("\n\nESC pressed. Saving partial transfer...")
                _finalize_sequential(
                    received_chunks, total_frames_expected,
                    expected_file_size, expected_sha256,
                    expected_filename, output_dir, start_time,
                    bytes_per_frame=profile.seq_bytes_per_frame,
                )
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
    *,
    bytes_per_frame: int,
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
            full_data.extend(b"\x00" * bytes_per_frame)

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
    cap: object,
    output_dir: str,
    profile: ResolutionProfile,
) -> None:
    """Run the fountain receive loop (continuous droplets until complete)."""
    decoder: FountainDecoder | None = None
    tracker: ProgressTracker | None = None
    start_time: float | None = None
    start_ns: int | None = None
    bytes_received: int = 0
    fps_reporter = FPSReporter(report_interval_s=2.0)
    capture_fps_str = ""

    print("Fountain mode: waiting for first valid droplet...")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.001)  # avoid CPU spin when buffer is empty
            continue

        fps = fps_reporter.tick()
        if fps is not None:
            capture_fps_str = f" | Capture: {fps:.1f} FPS"

        if frame.shape[0] != profile.height or frame.shape[1] != profile.width:
            frame = cv2.resize(frame, (profile.width, profile.height))

        sampled = sample_frame(frame, profile.rows, profile.cols, profile.block_size)
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
                start_ns = time.perf_counter_ns()
                estimated_bytes = K * len(payload)
                tracker = ProgressTracker(K, estimated_bytes)

            if decoder.K == K:
                decoder.add_droplet(seed, payload)
                bytes_received += len(payload)
                progress = len(decoder.chunks) / K

                # Build speed/ETA string using ProgressTracker
                if tracker is not None and start_ns is not None:
                    elapsed = time.perf_counter_ns() - start_ns
                    if elapsed > 2e9:  # after 2s warmup
                        speed = bytes_received / (elapsed / 1e9)
                        remaining = (K - len(decoder.chunks)) * len(payload)
                        eta = remaining / speed if speed > 0 else float("inf")
                        eta_str = (
                            f" | {speed / 1024:.1f} KB/s"
                            f" | ETA: {ProgressTracker._format_eta(eta)}"
                        )
                    else:
                        eta_str = " | ETA: --:--"
                else:
                    eta_str = ""

                sys.stdout.write(
                    f"\rProgress: {progress:.1%} ({len(decoder.chunks)}/{K})"
                    f"{eta_str}{capture_fps_str}"
                )
                sys.stdout.flush()

                if decoder.is_complete():
                    print("\nDownload complete!")
                    _finalize_fountain(decoder, output_dir, start_time)
                    _print_capture_stats(cap)
                    break

        # Debug window
        debug_frame = frame.copy()
        _draw_grid_overlay(
            debug_frame, sequential=False,
            rows=profile.rows, cols=profile.cols,
            block_size=profile.block_size,
            width=profile.width, height=profile.height,
        )
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
    cap: object,
    output_dir: str,
    profile: ResolutionProfile,
) -> None:
    """Auto-detect protocol from magic number and delegate."""
    seq = get_protocol("sequential", profile=profile)
    fount = get_protocol("fountain", profile=profile)

    print("Auto mode: probing frames for protocol magic number...")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.001)  # avoid CPU spin when buffer is empty
            continue

        if frame.shape[0] != profile.height or frame.shape[1] != profile.width:
            frame = cv2.resize(frame, (profile.width, profile.height))

        sampled = sample_frame(frame, profile.rows, profile.cols, profile.block_size)

        # Try sequential first (3-bit encoding)
        seq_result = seq.decode_frame(sampled)
        if seq_result.is_valid:
            print("Detected SEQUENTIAL protocol.")
            _receive_sequential(seq, cap, output_dir, profile)
            return

        # Try fountain (3-bit encoding)
        fount_result = fount.decode_frame(sampled)
        if fount_result.is_valid:
            print("Detected FOUNTAIN protocol.")
            _receive_fountain(fount, cap, output_dir, profile)
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

def _draw_grid_overlay(
    frame: np.ndarray,
    sequential: bool = True,
    *,
    rows: int,
    cols: int,
    block_size: int,
    width: int,
    height: int,
) -> None:
    """Draw debug grid overlay on *frame* (in-place)."""
    step = 5 if sequential else 10
    color = (0, 255, 255) if sequential else (0, 0, 255)

    for r in range(0, rows, step):
        y = r * block_size
        cv2.line(frame, (0, y), (width, y), color, 1)
    for c in range(0, cols, step):
        x = c * block_size
        cv2.line(frame, (x, 0), (x, height), color, 1)


def _print_receive_stats(total_bytes: int, start_time: float) -> None:
    """Print timing and throughput statistics."""
    duration = time.time() - start_time
    speed = (total_bytes * 8) / duration / 1_000_000 if duration > 0 else 0
    print(f"Time: {duration:.2f}s, Speed: {speed:.2f} Mbps")


def _print_capture_stats(cap: object) -> None:
    """Print capture thread statistics if available."""
    if hasattr(cap, "capture_fps_reporter"):
        reporter = cap.capture_fps_reporter
        print(f"Capture: {reporter.total_frames} frames captured")


def _run_receiver(
    source: object,
    mode: str,
    output: str,
    profile: ResolutionProfile,
) -> None:
    """Dispatch to the appropriate receive mode."""
    if mode == "auto":
        _receive_auto(source, output, profile)
    elif mode == "sequential":
        seq = get_protocol("sequential", profile=profile)
        _receive_sequential(seq, source, output, profile)
    else:
        fount = get_protocol("fountain", profile=profile)
        _receive_fountain(fount, source, output, profile)


# ------------------------------------------------------------------
# run_receive -- primary API
# ------------------------------------------------------------------

def run_receive(
    source: int | str,
    mode: str = "auto",
    profile: ResolutionProfile | None = None,
    output: str = "received_files",
    threaded: bool = True,
    buffer_size: int = 16,
) -> None:
    """Execute the full receive pipeline with explicit parameters.

    This is the primary API for receiving files over HDMI.  Called by both
    the ``hdmi-recv`` CLI and the interactive ``hdmi-receiver`` console.

    Parameters
    ----------
    source:
        Camera index (int) or video file path (str).
    mode:
        Decoding protocol: ``"auto"``, ``"sequential"``, or ``"fountain"``.
    profile:
        Resolution profile.  Defaults to *DEFAULT_PROFILE* if ``None``.
    output:
        Directory to save received files.
    threaded:
        Use threaded capture with ring buffer.
    buffer_size:
        Ring buffer size for threaded capture.
    """
    profile = profile or DEFAULT_PROFILE

    # Parse source: numeric string -> camera index
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    print(f"Opening video source: {source}")

    try:
        cap = CaptureSource(
            source, width=profile.width, height=profile.height,
            fps=profile.target_fps,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return  # Return to caller (menu or CLI), don't sys.exit()

    print(
        f"Camera: {cap.actual_width}x{cap.actual_height} "
        f"@ {cap.actual_fps} FPS"
    )

    with cap:
        if threaded:
            tcap = ThreadedCapture(cap, buffer_size=buffer_size)
            with tcap:
                print(f"Threaded capture: buffer_size={buffer_size} frames")
                _run_receiver(tcap, mode, output, profile)
        else:
            _run_receiver(cap, mode, output, profile)


# ------------------------------------------------------------------
# main -- thin CLI wrapper
# ------------------------------------------------------------------

def main() -> None:
    """Entry point for ``hdmi-recv`` CLI command."""
    parser = _build_parser()
    args = parser.parse_args()

    run_receive(
        source=args.source,
        mode=args.mode,
        profile=PROFILES[args.profile] if args.profile else None,
        output=args.output,
        threaded=args.threaded,
        buffer_size=args.buffer_size,
    )


if __name__ == "__main__":
    main()
