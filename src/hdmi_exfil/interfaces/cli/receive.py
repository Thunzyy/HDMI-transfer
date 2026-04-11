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

from hdmi_exfil.application.receive_session import ReceiveSession
from hdmi_exfil.core.capture.sampler import sample_frame
from hdmi_exfil.core.cli.progress import ProgressTracker
from hdmi_exfil.receiver.capture.source import CaptureSource
from hdmi_exfil.core.capture.threaded import FPSReporter, ThreadedCapture
from hdmi_exfil.core.config import (
    DEFAULT_PROFILE,
    PROFILES,
    ResolutionProfile,
)
from hdmi_exfil.core.file_handling.writer import write_output


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
# Shared receive loop
# ------------------------------------------------------------------

def _receive_with_session(
    cap: object,
    output_dir: str,
    profile: ResolutionProfile,
    *,
    mode: str,
) -> None:
    """Run the shared receive loop driven by ``ReceiveSession`` events."""
    session = ReceiveSession(mode=mode, profile=profile)
    fps_reporter = FPSReporter(report_interval_s=2.0)
    capture_fps_str = ""
    intro_message = {
        "auto": "Auto mode: probing frames for protocol magic number...",
        "sequential": "Sequential mode: capturing frames...",
        "fountain": "Fountain mode: waiting for first valid droplet...",
    }[mode]
    print(intro_message)
    window_name = {
        "auto": "Receiver (auto-detect)",
        "sequential": "Receiver View",
        "fountain": "Receiver Fountain",
    }[mode]

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
        events = session.feed_sampled_grid(sampled)
        for event in events:
            if event.kind == "status":
                message = str(event.data.get("message", ""))
                if message:
                    prefix = "\n" if event.data.get("state") == "detected" else ""
                    print(f"{prefix}{message}")
            elif event.kind == "progress":
                _print_cli_progress(event.data, capture_fps_str)
            elif event.kind == "complete":
                protocol = event.data.get("protocol")
                if protocol == "sequential":
                    print("\n\nAll frames received. Reassembling...")
                else:
                    print("\nDownload complete!")
                _handle_cli_complete(event.data, output_dir)
                _print_capture_stats(cap)
                cv2.destroyAllWindows()
                return

        # Debug window
        debug_frame = frame.copy()
        if session.detected_protocol in {"sequential", "fountain"}:
            _draw_grid_overlay(
                debug_frame,
                sequential=(session.detected_protocol == "sequential"),
                rows=profile.rows,
                cols=profile.cols,
                block_size=profile.block_size,
                width=profile.width,
                height=profile.height,
            )
        cv2.imshow(window_name, debug_frame)
        if cv2.waitKey(1) & 0xFF == 27:
            partial = session.finalize_partial()
            if partial is not None:
                print("\n\nESC pressed. Saving partial transfer...")
                _handle_cli_complete(partial.data, output_dir)
            break

    cv2.destroyAllWindows()


def _print_cli_progress(data: dict[str, object], capture_fps_str: str) -> None:
    """Render a progress event on the CLI status line."""
    protocol = data.get("protocol")
    if protocol == "sequential":
        total_chunks = int(data.get("total_chunks", 0) or 0)
        chunks_decoded = int(data.get("chunks_decoded", 0) or 0)
        percent = (chunks_decoded / total_chunks) if total_chunks else 0.0
        speed_kbps = float(data.get("speed_kbps", 0) or 0)
        eta_seconds = float(data.get("eta_seconds", -1) or -1)
        speed_str = f"{speed_kbps:.1f} KB/s" if speed_kbps > 0 else "-- KB/s"
        eta_str = (
            ProgressTracker._format_eta(eta_seconds)
            if eta_seconds >= 0
            else "--:--"
        )
        pass_count = int(data.get("pass_count", 0) or 0)
        pass_str = f" | Pass {pass_count + 1}" if pass_count > 0 else ""
        sys.stdout.write(
            f"\rFrames: {chunks_decoded}/{total_chunks} ({percent:.1%}) "
            f"| {speed_str} | ETA: {eta_str}{pass_str}{capture_fps_str}    "
        )
        sys.stdout.flush()
        return

    total_chunks = int(data.get("total_chunks", 0) or 0)
    chunks_decoded = int(data.get("chunks_decoded", 0) or 0)
    percent = float(data.get("percent", 0) or 0)
    speed_kbps = float(data.get("speed_kbps", 0) or 0)
    eta_seconds = float(data.get("eta_seconds", -1) or -1)
    if speed_kbps > 0 and eta_seconds >= 0:
        extra = (
            f" | {speed_kbps:.1f} KB/s"
            f" | ETA: {ProgressTracker._format_eta(eta_seconds)}"
        )
    else:
        extra = " | ETA: --:--"
    sys.stdout.write(
        f"\rProgress: {percent:.1f}% ({chunks_decoded}/{total_chunks})"
        f"{extra}{capture_fps_str}    "
    )
    sys.stdout.flush()


def _handle_cli_complete(
    data: dict[str, object],
    output_dir: str,
) -> None:
    """Persist a completed receive event and print final stats."""
    file_content = bytes(data["file_content"])
    filename = str(data["filename"])
    protocol = str(data.get("protocol", ""))
    sha256_available = bool(data.get("sha256_available"))
    sha256_ok = bool(data.get("sha256_ok"))

    if sha256_available:
        if sha256_ok:
            print("SHA-256 verified OK.")
        else:
            print("ERROR: SHA-256 MISMATCH -- file corrupted!")
    elif protocol == "fountain":
        print("Metadata decode failed. Saving raw payload.")

    missing_frames = data.get("missing_frames")
    if isinstance(missing_frames, list) and missing_frames:
        print(f"WARNING: Missing frames: {missing_frames}")

    save_path = write_output(file_content, filename, output_dir)
    print(f"Saved to {save_path}")
    duration = float(data.get("duration_s", 0) or 0)
    speed = float(data.get("speed_mbps", 0) or 0)
    print(f"Time: {duration:.2f}s, Speed: {speed:.2f} Mbps")


def _receive_sequential(
    cap: object,
    output_dir: str,
    profile: ResolutionProfile,
) -> None:
    _receive_with_session(cap, output_dir, profile, mode="sequential")


def _receive_fountain(
    cap: object,
    output_dir: str,
    profile: ResolutionProfile,
) -> None:
    _receive_with_session(cap, output_dir, profile, mode="fountain")


def _receive_auto(
    cap: object,
    output_dir: str,
    profile: ResolutionProfile,
) -> None:
    _receive_with_session(cap, output_dir, profile, mode="auto")


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
        _receive_sequential(source, output, profile)
    else:
        _receive_fountain(source, output, profile)


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
