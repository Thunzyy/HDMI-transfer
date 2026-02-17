"""CLI entry point for ``hdmi-send`` -- drives file transmission over HDMI.

Orchestrates file reading, protocol encoding, monitor detection, and frame
display.  Contains no encoding logic; it is a thin wiring layer over the
``hdmi_exfil`` package modules.

Usage::

    hdmi-send photo.png --mode sequential --fps 240 --screen 1
    hdmi-send secret.zip --mode fountain --fps 60
    hdmi-send secret.zip --renderer cv2 --mode fountain
    hdmi-send secret.zip --mode fountain --fountain-redundancy 1.05
    hdmi-send photo.png --profile quality --mode sequential
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import time

import numpy as np

from hdmi_exfil.config import (
    DEFAULT_PROFILE,
    PROFILES,
    ResolutionProfile,
)
from hdmi_exfil.display.monitors import get_monitors
from hdmi_exfil.display.renderer import FrameRenderer, PygameRenderer
from hdmi_exfil.file_handling.metadata import build_start_metadata
from hdmi_exfil.file_handling.reader import read_input
from hdmi_exfil.prng import choose_indices
from hdmi_exfil.protocols import get_protocol
from hdmi_exfil.protocols.xor_ops import warmup as warmup_numba, xor_into


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hdmi-send",
        description="HDMI Exfiltration Sender -- encode and display files as HDMI frames",
    )
    parser.add_argument("input_path", help="File or directory to send")
    parser.add_argument(
        "--mode",
        choices=["sequential", "fountain"],
        default="sequential",
        help="Encoding protocol (default: sequential)",
    )
    parser.add_argument(
        "--renderer",
        choices=["pygame", "cv2"],
        default="pygame",
        help="Display backend: pygame (SDL2 vsync, recommended) or cv2 (legacy). Default: pygame",
    )
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default=None,
        help="Resolution profile: speed (1080p@240fps), balanced (1080p@60fps), quality (4K@30fps)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=None,
        help="Target frames per second (overrides profile fps when both specified)",
    )
    parser.add_argument(
        "--redundancy",
        type=int,
        default=1,
        help="Times to repeat each frame (default: 1, sequential only)",
    )
    parser.add_argument(
        "--fountain-redundancy",
        type=float,
        default=None,
        help=(
            "Fountain mode: stop after K * REDUNDANCY droplets "
            "(e.g. 1.05 = 5%% overhead). Default: None (loop forever)."
        ),
    )
    parser.add_argument(
        "--screen",
        type=int,
        default=0,
        help="Monitor index for display (0=primary, default: 0)",
    )
    return parser


# ------------------------------------------------------------------
# Pause/resume UI helpers
# ------------------------------------------------------------------

_PAUSE_COLOR = (255, 165, 0)  # orange BGR
_DONE_COLOR = (0, 255, 0)  # green BGR
_INTERRUPTED_COLOR = (0, 0, 255)  # red BGR


def _solid_frame(
    bgr: tuple[int, int, int],
    profile: ResolutionProfile,
) -> np.ndarray:
    """Create a solid-color (H, W, 3) uint8 frame at *profile* resolution."""
    frame = np.zeros((profile.height, profile.width, 3), dtype=np.uint8)
    frame[:, :] = bgr
    return frame


def _show_pause_screen(
    renderer: FrameRenderer | PygameRenderer,
    profile: ResolutionProfile,
) -> str:
    """Display pause overlay and wait for user action.

    Returns ``'resume'``, ``'quit'``, or keeps looping until one of those.
    """
    pause_img = _solid_frame(_PAUSE_COLOR, profile)
    print("PAUSED -- Press 'r' to RESUME, 'q' or ESC to QUIT")
    while True:
        key = renderer.show(pause_img, delay_ms=100)
        if key == ord("r"):
            return "resume"
        if key == 27 or key == ord("q"):
            return "quit"


def _show_end_screen(
    renderer: FrameRenderer | PygameRenderer,
    interrupted: bool,
    profile: ResolutionProfile,
) -> None:
    """Display completion or interruption screen."""
    if interrupted:
        end_img = _solid_frame(_INTERRUPTED_COLOR, profile)
        print("INTERRUPTED -- Press any key to exit")
        renderer.show(end_img, delay_ms=0)  # waitKey(0) = wait forever
    else:
        end_img = _solid_frame(_DONE_COLOR, profile)
        print("DONE")
        renderer.show(end_img, delay_ms=5000)


# ------------------------------------------------------------------
# Sequential send loop
# ------------------------------------------------------------------

def _send_sequential(
    protocol: object,
    filename: str,
    file_data: bytes,
    renderer: FrameRenderer | PygameRenderer,
    delay: int,
    redundancy: int,
    profile: ResolutionProfile,
) -> None:
    """Run the sequential send loop (START -> DATA -> END)."""
    bytes_per_frame = profile.seq_bytes_per_frame
    total_frames = math.ceil(len(file_data) / bytes_per_frame)
    print(f"Total DATA frames needed: {total_frames}")

    start_time = time.time()
    interrupted = False
    paused = False

    # Phase 1: START frame
    start_frame = protocol.encode_start_frame(filename, file_data, total_frames)
    for _ in range(redundancy):
        key = renderer.show(start_frame, delay_ms=delay)
        if key == 27:
            paused = True
            break

    # Phase 2: DATA frames
    i = 0
    while i < total_frames:
        if paused:
            action = _show_pause_screen(renderer, profile)
            if action == "quit":
                interrupted = True
                break
            paused = False
            print("\nResuming transmission...")
            continue

        start_byte = i * bytes_per_frame
        end_byte = min((i + 1) * bytes_per_frame, len(file_data))
        chunk = file_data[start_byte:end_byte]

        frame = protocol.encode_frame(chunk, i, total_frames)

        for _ in range(redundancy):
            key = renderer.show(frame, delay_ms=delay)
            if key == 27:
                paused = True
                print(f"\nPaused at frame {i}/{total_frames}")
                break

        if paused:
            continue
        i += 1

        progress = (i) / total_frames
        sys.stdout.write(f"\rProgress: {progress:.1%} ({i}/{total_frames})")
        sys.stdout.flush()

    # Phase 3: END frame
    if not interrupted:
        end_frame = protocol.encode_end_frame(total_frames)
        for _ in range(redundancy):
            renderer.show(end_frame, delay_ms=delay)

    _print_stats(len(file_data), start_time, interrupted, i, total_frames)
    _show_end_screen(renderer, interrupted, profile)


# ------------------------------------------------------------------
# Fountain send loop
# ------------------------------------------------------------------

def _send_fountain(
    protocol: object,
    filename: str,
    file_data: bytes,
    renderer: FrameRenderer | PygameRenderer,
    delay: int,
    fountain_redundancy: float | None = None,
    profile: ResolutionProfile = DEFAULT_PROFILE,
) -> None:
    """Run the fountain send loop (continuous droplets until user stops).

    Parameters
    ----------
    fountain_redundancy:
        If set, stop after ``K * fountain_redundancy`` droplets.
        For example 1.05 sends 5% more droplets than chunks.
        If ``None``, loop forever (backward-compatible).
    """
    payload_size = profile.fount_bytes_per_frame

    # Wrap metadata + content (same format as sender.html)
    metadata = build_start_metadata(filename, file_data)
    wrapped = metadata + file_data

    # Slice into chunks as numpy arrays (Numba-compatible)
    K = math.ceil(len(wrapped) / payload_size)

    chunks: list[np.ndarray] = []
    for i in range(K):
        start = i * payload_size
        end = min(start + payload_size, len(wrapped))
        chunk = np.zeros(payload_size, dtype=np.uint8)
        chunk[:end - start] = np.frombuffer(wrapped[start:end], dtype=np.uint8)
        chunks.append(chunk)

    # Compute optional droplet limit from redundancy factor
    max_droplets: int | None = None
    if fountain_redundancy is not None:
        max_droplets = int(math.ceil(K * fountain_redundancy))

    print(f"Fountain mode: K={K} chunks, payload_size={payload_size}")
    if max_droplets is not None:
        print(f"Redundancy: {fountain_redundancy}x -> {max_droplets} droplets")
    else:
        print("Sending droplets continuously. Press ESC to stop.")

    start_time = time.time()
    seed = 1
    frame_count = 0
    interrupted = False
    paused = False

    while True:
        # Stop if redundancy limit reached
        if max_droplets is not None and frame_count >= max_droplets:
            break

        if paused:
            action = _show_pause_screen(renderer, profile)
            if action == "quit":
                interrupted = True
                break
            paused = False
            print("\nResuming transmission...")
            continue

        # Build droplet payload by XOR-ing selected chunks (RSD via choose_indices)
        indices = choose_indices(seed, K)

        payload = np.zeros(payload_size, dtype=np.uint8)
        for idx in indices:
            xor_into(payload, chunks[idx])

        frame = protocol.encode_frame(
            payload.tobytes(), frame_count, K, seed=seed,
        )

        key = renderer.show(frame, delay_ms=delay)
        if key == 27:
            paused = True
            continue

        seed = (seed + 1) & 0xFFFFFFFF
        if seed == 0:
            seed = 1
        frame_count += 1

        if frame_count % 30 == 0:
            elapsed = time.time() - start_time
            fps_actual = frame_count / elapsed if elapsed > 0 else 0
            sys.stdout.write(
                f"\rFrames: {frame_count} | Seed: {seed} | "
                f"FPS: {fps_actual:.1f}"
            )
            sys.stdout.flush()

    _print_stats(len(file_data), start_time, interrupted, frame_count, None)
    _show_end_screen(renderer, interrupted, profile)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

def _print_stats(
    file_size: int,
    start_time: float,
    interrupted: bool,
    frames_sent: int,
    total_frames: int | None,
) -> None:
    """Print timing and throughput statistics."""
    duration = time.time() - start_time
    speed = (file_size * 8) / duration / 1_000_000 if duration > 0 else 0

    print()  # newline after progress
    if interrupted:
        msg = f"Transmission INTERRUPTED after {frames_sent} frames."
        if total_frames is not None:
            msg += f" ({frames_sent}/{total_frames})"
        print(msg)
    else:
        print("Transmission complete.")

    print(f"Time: {duration:.2f}s")
    print(f"Average Speed: {speed:.2f} Mbps")


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------

def main() -> None:
    """Entry point for ``hdmi-send`` CLI command."""
    parser = _build_parser()
    args = parser.parse_args()

    # Resolve profile
    if args.profile:
        profile = PROFILES[args.profile]
    else:
        profile = DEFAULT_PROFILE

    # Individual overrides: --fps beats profile target_fps
    target_fps = args.fps if args.fps is not None else profile.target_fps

    # Read input file / directory
    try:
        filename, file_data = read_input(args.input_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    file_size = len(file_data)
    sha256_hex = hashlib.sha256(file_data).hexdigest()

    print(f"Sending '{filename}' ({file_size} bytes)")
    print(f"SHA-256: {sha256_hex}")
    print(f"Resolution: {profile.width}x{profile.height}, Block Size: {profile.block_size}")
    print(f"Profile: {profile.name}")
    print(f"Mode: {args.mode}")
    print(f"Renderer: {args.renderer}")

    # Detect monitors
    monitors = get_monitors()
    print(f"\nDetected {len(monitors)} monitor(s):")
    for i, m in enumerate(monitors):
        print(f"  Monitor {i}: {m['width']}x{m['height']} at ({m['left']}, {m['top']})")

    if args.screen < len(monitors):
        target = monitors[args.screen]
        x_offset = target["left"]
        y_offset = target["top"]
    else:
        print(f"Warning: Screen {args.screen} out of range. Using primary.")
        x_offset = 0
        y_offset = 0

    print(f"Targeting screen {args.screen} at ({x_offset}, {y_offset})")

    # Instantiate protocol with profile
    protocol = get_protocol(args.mode, profile=profile)

    delay = max(1, int(1000 / target_fps))
    print(f"Target FPS: {target_fps} (delay: {delay}ms)")

    # Choose renderer based on --renderer flag
    if args.renderer == "pygame":
        renderer_cls = PygameRenderer
        renderer_kwargs: dict = {
            "width": profile.width,
            "height": profile.height,
            "x_offset": x_offset,
            "y_offset": y_offset,
        }
    else:
        renderer_cls = FrameRenderer
        renderer_kwargs = {
            "window_name": "HDMI Exfil Sender",
            "x_offset": x_offset,
            "y_offset": y_offset,
        }

    # Create renderer and show calibration frame
    with renderer_cls(**renderer_kwargs) as renderer:
        # Calibration frame: solid white border on black (works for both renderers)
        calibration = np.zeros((profile.height, profile.width, 3), dtype=np.uint8)
        calibration[0:5, :] = 255
        calibration[-5:, :] = 255
        calibration[:, 0:5] = 255
        calibration[:, -5:] = 255
        print("Press any key to start...")

        # Warm up Numba JIT during calibration wait (before data transfer)
        if args.mode == "fountain":
            warmup_numba()

        renderer.show(calibration, delay_ms=0)

        # Dispatch to mode-specific send loop
        if args.mode == "sequential":
            print(f"Redundancy: {args.redundancy}x")
            _send_sequential(
                protocol, filename, file_data, renderer,
                delay, args.redundancy, profile,
            )
        else:
            _send_fountain(
                protocol, filename, file_data, renderer, delay,
                fountain_redundancy=args.fountain_redundancy,
                profile=profile,
            )


if __name__ == "__main__":
    main()
