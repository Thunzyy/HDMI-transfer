"""CLI entry point for ``hdmi-calibrate`` -- display and analyze test patterns.

Provides three subcommands:

* ``hdmi-calibrate send`` -- display a checkerboard calibration pattern
* ``hdmi-calibrate recv <source>`` -- capture and analyze a calibration pattern
* ``hdmi-calibrate loopback <source>`` -- display, capture, and analyze

Usage::

    hdmi-calibrate send --profile speed
    hdmi-calibrate recv 0 --profile speed
    hdmi-calibrate loopback 0 --profile speed
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np

from hdmi_exfil.core.config import DEFAULT_PROFILE, PROFILES, ResolutionProfile
from hdmi_exfil.sender.display.test_patterns import (
    compute_alignment,
    compute_snr,
    generate_checkerboard,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hdmi-calibrate",
        description="HDMI Exfiltration Calibration -- display and analyze test patterns",
    )
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default="speed",
        help="Resolution profile (default: speed)",
    )

    sub = parser.add_subparsers(dest="command", help="Calibration mode")

    # send subcommand
    send_parser = sub.add_parser("send", help="Display calibration pattern on screen")
    send_parser.add_argument(
        "--renderer",
        choices=["cv2", "pygame"],
        default="cv2",
        help="Display backend (default: cv2)",
    )

    # recv subcommand
    recv_parser = sub.add_parser(
        "recv", help="Capture and analyze calibration pattern"
    )
    recv_parser.add_argument(
        "source",
        help="Camera index (integer) or video file path",
    )
    recv_parser.add_argument(
        "--frames",
        type=int,
        default=10,
        help="Number of frames to average for noise reduction (default: 10)",
    )
    recv_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save captured frame (optional)",
    )

    # loopback subcommand
    lb_parser = sub.add_parser(
        "loopback", help="Display pattern, capture, and analyze (same machine)"
    )
    lb_parser.add_argument(
        "source",
        help="Camera index (integer) or video file path",
    )
    lb_parser.add_argument(
        "--frames",
        type=int,
        default=10,
        help="Number of frames to average (default: 10)",
    )

    return parser


def _quality_label(snr_db: float) -> str:
    """Return a human-readable signal quality label from SNR in dB."""
    if snr_db > 30.0:
        return "EXCELLENT"
    if snr_db > 20.0:
        return "GOOD"
    if snr_db > 10.0:
        return "FAIR"
    return "POOR"


def _recommend_block_size(snr_db: float, current_bs: int) -> str:
    """Return block size recommendation based on SNR."""
    if snr_db > 30.0:
        return f"Current block_size={current_bs} is optimal"
    if snr_db > 20.0:
        suggestion = max(current_bs, 8)
        return f"block_size={suggestion} recommended (current: {current_bs})"
    if snr_db > 10.0:
        suggestion = max(current_bs * 2, 16)
        return f"Increase to block_size={suggestion} for reliability"
    suggestion = max(current_bs * 4, 32)
    return f"Poor signal -- try block_size={suggestion} or check HDMI connection"


def _open_capture(source: str) -> cv2.VideoCapture:
    """Open a video capture source (camera index or file path)."""
    try:
        idx = int(source)
        cap = cv2.VideoCapture(idx)
    except ValueError:
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"Error: cannot open capture source '{source}'")
        sys.exit(1)

    return cap


def _capture_averaged_frame(
    cap: cv2.VideoCapture,
    n_frames: int,
    profile: ResolutionProfile,
) -> np.ndarray:
    """Capture *n_frames* and return the averaged frame (noise reduction)."""
    accumulator: np.ndarray | None = None
    captured = 0

    for _ in range(n_frames + 5):  # extra reads to skip initial buffer
        ret, frame = cap.read()
        if not ret:
            continue

        # Resize to expected dimensions
        if frame.shape[1] != profile.width or frame.shape[0] != profile.height:
            frame = cv2.resize(frame, (profile.width, profile.height))

        if captured < 5:
            # Skip first 5 frames (auto-exposure settling)
            captured += 1
            continue

        if accumulator is None:
            accumulator = frame.astype(np.float64)
        else:
            accumulator += frame.astype(np.float64)
        captured += 1

        if captured >= n_frames + 5:
            break

    if accumulator is None:
        print("Error: no frames captured")
        sys.exit(1)

    n_averaged = captured - 5
    if n_averaged < 1:
        n_averaged = 1

    averaged = (accumulator / n_averaged).astype(np.uint8)
    return averaged


def _print_results(
    offset: tuple[int, int],
    snr_db: float,
    profile: ResolutionProfile,
) -> None:
    """Print calibration analysis results."""
    quality = _quality_label(snr_db)
    recommendation = _recommend_block_size(snr_db, profile.block_size)

    print("\nCalibration Results:")
    print(f"  Alignment offset: ({offset[0]}, {offset[1]}) pixels")
    print(f"  SNR: {snr_db:.1f} dB")
    print(f"  Signal quality: {quality}")
    print(f"  Recommended: {recommendation}")


def _cmd_send(profile: ResolutionProfile, args: argparse.Namespace) -> None:
    """Execute the ``send`` subcommand -- display calibration pattern."""
    pattern = generate_checkerboard(profile)
    print(
        f"Displaying calibration pattern ({profile.width}x{profile.height}, "
        f"block_size={profile.block_size})"
    )
    print("Press any key to exit.")

    renderer_name = getattr(args, "renderer", "cv2")

    if renderer_name == "pygame":
        from hdmi_exfil.sender.display.renderer import PygameRenderer

        with PygameRenderer(
            width=profile.width, height=profile.height
        ) as renderer:
            while True:
                key = renderer.show(pattern, delay_ms=100)
                if key != 255:
                    break
    else:
        cv2.imshow("Calibration Pattern", pattern)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def _cmd_recv(profile: ResolutionProfile, args: argparse.Namespace) -> None:
    """Execute the ``recv`` subcommand -- capture and analyze."""
    expected = generate_checkerboard(profile)

    cap = _open_capture(args.source)
    print(f"Capturing {args.frames} frames from source '{args.source}'...")

    captured = _capture_averaged_frame(cap, args.frames, profile)
    cap.release()

    # Save captured frame if output_dir specified
    output_dir = getattr(args, "output_dir", None)
    if output_dir is not None:
        import os

        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, "calibration_capture.png")
        cv2.imwrite(path, captured)
        print(f"Saved captured frame to {path}")

    # Analyze
    offset = compute_alignment(captured, expected)
    snr_db = compute_snr(captured, expected, profile.block_size)

    _print_results(offset, snr_db, profile)


def _cmd_loopback(profile: ResolutionProfile, args: argparse.Namespace) -> None:
    """Execute the ``loopback`` subcommand -- display, capture, analyze."""
    expected = generate_checkerboard(profile)

    # Display pattern
    print(
        f"Displaying calibration pattern ({profile.width}x{profile.height})..."
    )
    cv2.imshow("Calibration Pattern", expected)
    cv2.waitKey(1)  # Ensure display is rendered

    # Wait for display to stabilize
    print("Waiting 2s for display to stabilize...")
    time.sleep(2)

    # Capture
    cap = _open_capture(args.source)
    print(f"Capturing {args.frames} frames...")
    captured = _capture_averaged_frame(cap, args.frames, profile)
    cap.release()

    cv2.destroyAllWindows()

    # Analyze
    offset = compute_alignment(captured, expected)
    snr_db = compute_snr(captured, expected, profile.block_size)

    _print_results(offset, snr_db, profile)


def main() -> None:
    """Entry point for ``hdmi-calibrate`` CLI command."""
    parser = _build_parser()
    args = parser.parse_args()

    profile = PROFILES.get(args.profile, DEFAULT_PROFILE)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "send":
        _cmd_send(profile, args)
    elif args.command == "recv":
        _cmd_recv(profile, args)
    elif args.command == "loopback":
        _cmd_loopback(profile, args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
