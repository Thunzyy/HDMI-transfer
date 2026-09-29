"""CLI entry point for ``hdmi-send`` -- drives file transmission over HDMI.

Orchestrates file reading, protocol encoding, monitor detection, and frame
display.  Contains no encoding logic; it is a thin wiring layer over the
``hdmi_transfer`` package modules.

Usage::

    hdmi-send photo.png --mode sequential --fps 240 --screen 1
    hdmi-send secret.zip --mode fountain --fps 60
    hdmi-send secret.zip --renderer cv2 --mode fountain
    hdmi-send secret.zip --mode fountain --fountain-redundancy 1.05
    hdmi-send photo.png --profile quality --mode sequential
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

from hdmi_transfer.application.send_session import SendSession
from hdmi_transfer.core.config import (
    DEFAULT_PROFILE,
    PROFILES,
    ResolutionProfile,
)
from hdmi_transfer.sender.display.monitors import get_monitors
from hdmi_transfer.sender.display.renderer import FrameRenderer, PygameRenderer
from hdmi_transfer.core.protocols.xor_ops import warmup as warmup_numba


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hdmi-send",
        description="HDMI Transfer Sender -- encode and display files as HDMI frames",
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
        print("Stopped. Press any key to exit.")
        renderer.show(end_img, delay_ms=0)


# ------------------------------------------------------------------
# Sequential send loop
# ------------------------------------------------------------------

def _send_sequential(
    session: SendSession,
    renderer: FrameRenderer | PygameRenderer,
    delay: int,
    redundancy: int,
    profile: ResolutionProfile,
) -> None:
    """Run the sequential send loop, looping until user stops.

    Each pass sends START -> DATA -> END, then loops back.  The sender
    cannot know when the receiver is done, so it keeps transmitting
    until the user presses ESC and quits.
    """
    total_frames = session.total_frames
    print(f"Total DATA frames per pass: {total_frames}")
    print("Looping until you stop (ESC -> quit). Stop when receiver confirms.")

    start_time = time.time()
    pass_number = 0
    total_frames_sent = 0
    stopped = False

    while not stopped:
        paused = False
        packet_iter = iter(session.iter_frame_packets())
        current_packet = None
        current_repeats = 0
        frames_this_pass = 0

        while True:
            if paused:
                action = _show_pause_screen(renderer, profile)
                if action == "quit":
                    stopped = True
                    break
                paused = False
                print("\nResuming transmission...")
                continue

            if current_packet is None:
                try:
                    current_packet = next(packet_iter)
                except StopIteration:
                    break
                current_repeats = 0

            key = renderer.show(current_packet.frame, delay_ms=delay)
            if key == 27:
                paused = True
                if current_packet.kind == "data":
                    print(
                        f"\nPaused at frame "
                        f"{current_packet.frame_index}/{total_frames}"
                    )
                continue

            current_repeats += 1
            if current_repeats < redundancy:
                continue

            if current_packet.kind == "data":
                frames_this_pass += 1
                progress = (
                    frames_this_pass / total_frames if total_frames > 0 else 1.0
                )
                pass_label = (
                    f"Pass {pass_number + 1}" if pass_number > 0 else "Pass 1"
                )
                sys.stdout.write(
                    f"\r{pass_label}: {progress:.1%} "
                    f"({frames_this_pass}/{total_frames})"
                )
                sys.stdout.flush()

            current_packet = None

        if stopped:
            total_frames_sent += frames_this_pass
            break

        pass_number += 1
        total_frames_sent += frames_this_pass
        print(
            f"\nPass {pass_number} complete ({total_frames_sent} frames total). "
            "Looping... (ESC to stop)"
        )

    _print_stats(session.file_size, start_time, False, total_frames_sent, None)
    _show_end_screen(renderer, False, profile)


# ------------------------------------------------------------------
# Fountain send loop
# ------------------------------------------------------------------

def _send_fountain(
    session: SendSession,
    renderer: FrameRenderer | PygameRenderer,
    delay: int,
    profile: ResolutionProfile = DEFAULT_PROFILE,
) -> None:
    """Run the fountain send loop (continuous droplets until user stops).
    """
    print(
        f"Fountain mode: K={session.total_frames} chunks, "
        f"payload_size={session.bytes_per_frame}"
    )
    if session.max_droplets is not None:
        print(
            f"Redundancy limit: {session.max_droplets} droplets "
            f"({session.max_droplets / session.total_frames:.2f}x)"
        )
    else:
        print("Sending droplets continuously. Press ESC to stop.")

    start_time = time.time()
    frame_count = 0
    interrupted = False
    paused = False
    packet_iter = iter(session.iter_frame_packets())
    current_packet = None

    while True:
        if paused:
            action = _show_pause_screen(renderer, profile)
            if action == "quit":
                interrupted = True
                break
            paused = False
            print("\nResuming transmission...")
            continue

        if current_packet is None:
            try:
                current_packet = next(packet_iter)
            except StopIteration:
                break

        key = renderer.show(current_packet.frame, delay_ms=delay)
        if key == 27:
            paused = True
            continue

        frame_count += 1
        current_packet = None

        if frame_count % 30 == 0:
            elapsed = time.time() - start_time
            fps_actual = frame_count / elapsed if elapsed > 0 else 0
            sys.stdout.write(
                f"\rFrames: {frame_count} | "
                f"FPS: {fps_actual:.1f}"
            )
            sys.stdout.flush()

    _print_stats(session.file_size, start_time, interrupted, frame_count, None)
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
        print(f"Transmission stopped. {frames_sent} frames sent.")

    print(f"Time: {duration:.2f}s")
    print(f"Average Speed: {speed:.2f} Mbps")


# ------------------------------------------------------------------
# run_send -- core send logic callable without argparse
# ------------------------------------------------------------------

def run_send(
    input_path: str,
    mode: str = "sequential",
    profile: ResolutionProfile | None = None,
    renderer_type: str = "pygame",
    screen: int = 0,
    fps: int | None = None,
    redundancy: int = 1,
    fountain_redundancy: float | None = None,
) -> None:
    """Execute the full send pipeline with explicit parameters.

    This is the core send logic extracted from ``main()`` so that both
    the CLI (``hdmi-send``) and the interactive console (``hdmi-sender``)
    can share the same code path.

    Parameters
    ----------
    input_path:
        Path to the file or directory to send.
    mode:
        Encoding protocol -- ``"sequential"`` or ``"fountain"``.
    profile:
        Resolution profile.  ``None`` falls back to ``DEFAULT_PROFILE``.
    renderer_type:
        Display backend -- ``"pygame"`` or ``"cv2"``.
    screen:
        Monitor index for display (0 = primary).
    fps:
        Target frames per second.  ``None`` uses ``profile.target_fps``.
    redundancy:
        Times to repeat each frame (sequential mode only).
    fountain_redundancy:
        Fountain mode: stop after ``K * fountain_redundancy`` droplets.
        ``None`` loops forever.
    """
    # Resolve profile
    profile = profile or DEFAULT_PROFILE

    # Individual overrides: --fps beats profile target_fps
    target_fps = fps if fps is not None else profile.target_fps

    try:
        session = SendSession.from_input(
            input_path=input_path,
            mode=mode,
            profile=profile,
            fountain_redundancy=fountain_redundancy,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    print(f"Sending '{session.filename}' ({session.file_size} bytes)")
    print(f"SHA-256: {session.sha256_hex}")
    print(f"Resolution: {profile.width}x{profile.height}, Block Size: {profile.block_size}")
    print(f"Profile: {profile.name}")
    print(f"Mode: {session.mode}")
    print(f"Renderer: {renderer_type}")

    # Detect monitors
    monitors = get_monitors()
    print(f"\nDetected {len(monitors)} monitor(s):")
    for i, m in enumerate(monitors):
        print(f"  Monitor {i}: {m['width']}x{m['height']} at ({m['left']}, {m['top']})")

    if screen < len(monitors):
        target = monitors[screen]
        x_offset = target["left"]
        y_offset = target["top"]
    else:
        print(f"Warning: Screen {screen} out of range. Using primary.")
        x_offset = 0
        y_offset = 0

    print(f"Targeting screen {screen} at ({x_offset}, {y_offset})")

    delay = max(1, int(1000 / target_fps))
    print(f"Target FPS: {target_fps} (delay: {delay}ms)")

    # Choose renderer based on renderer_type
    if renderer_type == "pygame":
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
            "window_name": "HDMI Transfer Sender",
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
        if session.mode == "fountain":
            warmup_numba()

        renderer.show(calibration, delay_ms=0)

        # Dispatch to mode-specific send loop
        if session.mode == "sequential":
            print(f"Redundancy: {redundancy}x")
            _send_sequential(
                session, renderer,
                delay, redundancy, profile,
            )
        else:
            _send_fountain(
                session, renderer, delay,
                profile=profile,
            )


# ------------------------------------------------------------------
# main -- thin CLI wrapper
# ------------------------------------------------------------------

def main() -> None:
    """Entry point for ``hdmi-send`` CLI command."""
    parser = _build_parser()
    args = parser.parse_args()
    run_send(
        input_path=args.input_path,
        mode=args.mode,
        profile=PROFILES[args.profile] if args.profile else None,
        renderer_type=args.renderer,
        screen=args.screen,
        fps=args.fps,
        redundancy=args.redundancy,
        fountain_redundancy=args.fountain_redundancy,
    )


if __name__ == "__main__":
    main()
