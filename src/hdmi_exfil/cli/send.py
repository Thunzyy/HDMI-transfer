"""CLI entry point for ``hdmi-send`` -- drives file transmission over HDMI.

Orchestrates file reading, protocol encoding, monitor detection, and frame
display.  Contains no encoding logic; it is a thin wiring layer over the
``hdmi_exfil`` package modules.

Usage::

    hdmi-send photo.png --mode sequential --fps 240 --screen 1
    hdmi-send secret.zip --mode fountain --fps 60
    hdmi-send secret.zip --renderer cv2 --mode fountain
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import time

import numpy as np

from hdmi_exfil.config import (
    BLOCK_SIZE,
    BYTES_PER_FRAME,
    HEIGHT,
    WIDTH,
)
from hdmi_exfil.display.monitors import get_monitors
from hdmi_exfil.display.renderer import FrameRenderer, PygameRenderer
from hdmi_exfil.file_handling.metadata import build_start_metadata
from hdmi_exfil.file_handling.reader import read_input
from hdmi_exfil.protocols import get_protocol
from hdmi_exfil.protocols.fountain import PAYLOAD_SIZE as FOUNTAIN_PAYLOAD_SIZE
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
        "--fps",
        type=int,
        default=240,
        help="Target frames per second (default: 240)",
    )
    parser.add_argument(
        "--redundancy",
        type=int,
        default=1,
        help="Times to repeat each frame (default: 1, sequential only)",
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


def _solid_frame(bgr: tuple[int, int, int]) -> np.ndarray:
    """Create a solid-color (H, W, 3) uint8 frame."""
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[:, :] = bgr
    return frame


def _show_pause_screen(renderer: FrameRenderer | PygameRenderer) -> str:
    """Display pause overlay and wait for user action.

    Returns ``'resume'``, ``'quit'``, or keeps looping until one of those.
    """
    pause_img = _solid_frame(_PAUSE_COLOR)
    print("PAUSED -- Press 'r' to RESUME, 'q' or ESC to QUIT")
    while True:
        key = renderer.show(pause_img, delay_ms=100)
        if key == ord("r"):
            return "resume"
        if key == 27 or key == ord("q"):
            return "quit"


def _show_end_screen(
    renderer: FrameRenderer | PygameRenderer, interrupted: bool,
) -> None:
    """Display completion or interruption screen."""
    if interrupted:
        end_img = _solid_frame(_INTERRUPTED_COLOR)
        print("INTERRUPTED -- Press any key to exit")
        renderer.show(end_img, delay_ms=0)  # waitKey(0) = wait forever
    else:
        end_img = _solid_frame(_DONE_COLOR)
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
) -> None:
    """Run the sequential send loop (START -> DATA -> END)."""
    total_frames = math.ceil(len(file_data) / BYTES_PER_FRAME)
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
            action = _show_pause_screen(renderer)
            if action == "quit":
                interrupted = True
                break
            paused = False
            print("\nResuming transmission...")
            continue

        start_byte = i * BYTES_PER_FRAME
        end_byte = min((i + 1) * BYTES_PER_FRAME, len(file_data))
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
    _show_end_screen(renderer, interrupted)


# ------------------------------------------------------------------
# Fountain send loop
# ------------------------------------------------------------------

def _send_fountain(
    protocol: object,
    filename: str,
    file_data: bytes,
    renderer: FrameRenderer | PygameRenderer,
    delay: int,
) -> None:
    """Run the fountain send loop (continuous droplets until user stops)."""
    # Wrap metadata + content (same format as sender.html)
    metadata = build_start_metadata(filename, file_data)
    wrapped = metadata + file_data

    # Slice into chunks as numpy arrays (Numba-compatible)
    K = math.ceil(len(wrapped) / FOUNTAIN_PAYLOAD_SIZE)

    chunks: list[np.ndarray] = []
    for i in range(K):
        start = i * FOUNTAIN_PAYLOAD_SIZE
        end = min(start + FOUNTAIN_PAYLOAD_SIZE, len(wrapped))
        chunk = np.zeros(FOUNTAIN_PAYLOAD_SIZE, dtype=np.uint8)
        chunk[:end - start] = np.frombuffer(wrapped[start:end], dtype=np.uint8)
        chunks.append(chunk)

    print(f"Fountain mode: K={K} chunks, payload_size={FOUNTAIN_PAYLOAD_SIZE}")
    print("Sending droplets continuously. Press ESC to stop.")

    start_time = time.time()
    seed = 1
    frame_count = 0
    interrupted = False
    paused = False

    while True:
        if paused:
            action = _show_pause_screen(renderer)
            if action == "quit":
                interrupted = True
                break
            paused = False
            print("\nResuming transmission...")
            continue

        # Build droplet payload by XOR-ing selected chunks (Numba-accelerated)
        from hdmi_exfil.prng import PRNG  # noqa: C0415

        prng = PRNG(seed)
        degree = 1
        r = prng.next_float()
        if r < 0.1:
            degree = 1
        elif r < 0.6:
            degree = 2
        else:
            degree = int(prng.next_float() * min(K, 20)) + 1
        degree = min(degree, K)

        indices: set[int] = set()
        while len(indices) < degree:
            idx = prng.next() % K
            indices.add(idx)

        payload = np.zeros(FOUNTAIN_PAYLOAD_SIZE, dtype=np.uint8)
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
    _show_end_screen(renderer, interrupted)


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
    print(f"Resolution: {WIDTH}x{HEIGHT}, Block Size: {BLOCK_SIZE}")
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

    # Instantiate protocol
    protocol = get_protocol(args.mode)

    delay = max(1, int(1000 / args.fps))
    print(f"Target FPS: {args.fps} (delay: {delay}ms)")

    # Choose renderer based on --renderer flag
    if args.renderer == "pygame":
        renderer_cls = PygameRenderer
        renderer_kwargs: dict = {
            "width": WIDTH,
            "height": HEIGHT,
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
        calibration = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
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
                delay, args.redundancy,
            )
        else:
            _send_fountain(
                protocol, filename, file_data, renderer, delay,
            )


if __name__ == "__main__":
    main()
