"""Measure verified in-memory encode/decode throughput, without HDMI hardware.

Payload preparation and a separate warm-up are excluded from the timed run.
The timed run includes encoding, sampling, reconstruction and byte comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, replace

import numpy as np

from hdmi_transfer.core.capture.sampler import sample_frame
from hdmi_transfer.core.config import PROFILES, ResolutionProfile
from hdmi_transfer.core.protocols import get_protocol
from hdmi_transfer.domain.transfer_defaults import (
    DEFAULT_BITS_PER_CHANNEL,
    DEFAULT_MODE,
    DEFAULT_PROFILE_NAME,
)


@dataclass
class BenchmarkResult:
    """Transfer metrics; error_rate describes frames, not file integrity."""

    profile: str
    mode: str
    frames_per_sec: float
    bytes_per_sec: float
    overhead_pct: float
    error_rate: float
    duration_sec: float
    total_frames: int
    total_bytes: int
    completed: bool = False
    integrity_ok: bool = False
    timed_out: bool = False
    payload_bytes: int = 0
    warmup_duration_sec: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _sample(profile: ResolutionProfile, frame: np.ndarray) -> np.ndarray:
    return sample_frame(frame, profile.rows, profile.cols, profile.block_size)


def _warmup_protocol(profile: ResolutionProfile, mode: str) -> float:
    """Load/compile the exercised path before starting the transfer timer."""
    started = time.perf_counter()
    proto = get_protocol(mode, profile=profile)
    payload = np.arange(proto.bytes_per_frame, dtype=np.uint8).tobytes()
    frame = proto.encode_frame(payload, 0, 1, seed=1)
    proto.decode_frame(_sample(profile, frame))
    if mode == "fountain":
        from hdmi_transfer.core.protocols.fountain import FountainDecoder
        from hdmi_transfer.core.protocols.xor_ops import warmup

        warmup()
        FountainDecoder(1, len(payload)).add_droplet(1, payload)
    return time.perf_counter() - started


def run_benchmark(
    profile: ResolutionProfile,
    mode: str,
    payload_size_kb: int = 100,
    duration_sec: float = 10.0,
) -> BenchmarkResult:
    """Benchmark one payload in KiB with a deadline for either protocol.

    total_bytes and bytes_per_sec count a completed, byte-verified payload,
    never padding or partial reconstruction. This does not measure display,
    capture or physical HDMI throughput. Warm-up is reported separately.
    """
    if mode not in ("sequential", "fountain"):
        raise ValueError(f"Unknown mode: {mode!r}")
    if (
        isinstance(payload_size_kb, bool)
        or not isinstance(payload_size_kb, int)
        or payload_size_kb <= 0
    ):
        raise ValueError("Payload size must be a positive integer in KiB")
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        raise ValueError("Duration must be a finite positive number of seconds")
    payload_per_frame = (
        profile.seq_bytes_per_frame if mode == "sequential"
        else profile.fount_bytes_per_frame
    )
    if payload_per_frame <= 0:
        raise ValueError("Profile has no room for a frame payload")
    if (
        mode == "fountain"
        and math.ceil(payload_size_kb * 1024 / payload_per_frame) > 60000
    ):
        raise ValueError("Payload exceeds the Fountain receiver's 60000-chunk limit")

    warmup_duration = _warmup_protocol(profile, mode)
    benchmark = _bench_sequential if mode == "sequential" else _bench_fountain
    result = benchmark(profile, payload_size_kb, duration_sec)
    result.warmup_duration_sec = round(warmup_duration, 6)
    return result


def _make_result(
    profile: ResolutionProfile, mode: str, *, elapsed: float, deadline: float,
    frame_count: int, errors: int, payload_bytes: int, completed: bool,
    integrity_ok: bool, overhead_pct: float = 0.0,
) -> BenchmarkResult:
    useful_bytes = payload_bytes if completed and integrity_ok else 0
    return BenchmarkResult(
        profile=profile.name, mode=mode,
        frames_per_sec=round(frame_count / elapsed, 2) if elapsed > 0 else 0.0,
        bytes_per_sec=round(useful_bytes / elapsed, 2) if elapsed > 0 else 0.0,
        overhead_pct=round(overhead_pct, 2),
        error_rate=round(errors / frame_count, 6) if frame_count else 0.0,
        duration_sec=round(elapsed, 6), total_frames=frame_count,
        total_bytes=useful_bytes, completed=completed, integrity_ok=integrity_ok,
        timed_out=elapsed >= deadline, payload_bytes=payload_bytes,
    )


def _bench_sequential(
    profile: ResolutionProfile, payload_size_kb: int, duration_sec: float,
) -> BenchmarkResult:
    proto = get_protocol("sequential", profile=profile)
    bpf = proto.bytes_per_frame
    payload = np.random.default_rng(0).bytes(payload_size_kb * 1024)
    total_frames = math.ceil(len(payload) / bpf)
    errors = 0
    frame_count = 0
    recovered: dict[int, bytes] = {}
    start = time.perf_counter()
    for index in range(total_frames):
        if time.perf_counter() - start >= duration_sec:
            break
        chunk = payload[index * bpf : (index + 1) * bpf]
        frame = proto.encode_frame(chunk, index, total_frames)
        result = proto.decode_frame(_sample(profile, frame))
        frame_count += 1
        if (
            result.is_valid
            and result.data is not None
            and result.frame_index == index
            and result.total_frames == total_frames
        ):
            recovered[index] = result.data
            if result.data != chunk:
                errors += 1
        else:
            errors += 1
    completed = len(recovered) == total_frames
    integrity_ok = completed and (
        b"".join(recovered[i] for i in range(total_frames)) == payload
    )
    elapsed = time.perf_counter() - start
    return _make_result(
        profile, "sequential", elapsed=elapsed, deadline=duration_sec,
        frame_count=frame_count, errors=errors, payload_bytes=len(payload),
        completed=completed, integrity_ok=integrity_ok,
    )


def _bench_fountain(
    profile: ResolutionProfile, payload_size_kb: int, duration_sec: float,
) -> BenchmarkResult:
    from hdmi_transfer.core.prng import choose_indices
    from hdmi_transfer.core.protocols.fountain import FountainDecoder
    from hdmi_transfer.core.protocols.xor_ops import xor_into

    proto = get_protocol("fountain", profile=profile)
    payload_per_frame = proto.bytes_per_frame
    raw_payload = np.random.default_rng(0).bytes(payload_size_kb * 1024)
    chunk_count = math.ceil(len(raw_payload) / payload_per_frame)
    chunks: list[np.ndarray] = []
    for index in range(chunk_count):
        data = raw_payload[index * payload_per_frame : (index + 1) * payload_per_frame]
        chunk = np.zeros(payload_per_frame, dtype=np.uint8)
        chunk[: len(data)] = np.frombuffer(data, dtype=np.uint8)
        chunks.append(chunk)
    decoder = FountainDecoder(chunk_count, payload_per_frame)
    seed = 1
    frame_count = 0
    errors = 0
    start = time.perf_counter()
    while not decoder.is_complete():
        if time.perf_counter() - start >= duration_sec:
            break
        drop_payload = np.zeros(payload_per_frame, dtype=np.uint8)
        for index in choose_indices(seed, chunk_count):
            xor_into(drop_payload, chunks[index])
        frame = proto.encode_frame(
            drop_payload.tobytes(), frame_count, chunk_count, seed=seed,
        )
        result = proto.decode_frame(_sample(profile, frame))
        frame_count += 1
        if (
            result.is_valid
            and result.data is not None
            and result.frame_index == seed
            and result.total_frames == chunk_count
        ):
            decoder.add_droplet(seed, result.data)
        else:
            errors += 1
        seed = ((seed + 1) & 0xFFFFFFFF) or 1
    completed = decoder.is_complete()
    # Fountain reconstruction includes zero padding in its last chunk.
    integrity_ok = completed and decoder.get_file_data()[: len(raw_payload)] == raw_payload
    elapsed = time.perf_counter() - start
    return _make_result(
        profile, "fountain", elapsed=elapsed, deadline=duration_sec,
        frame_count=frame_count, errors=errors, payload_bytes=len(raw_payload),
        completed=completed, integrity_ok=integrity_ok,
        overhead_pct=(frame_count - chunk_count) / chunk_count * 100 if completed else 0.0,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hdmi-bench",
        description="Measure verified in-memory encode/decode throughput (not HDMI throughput)",
    )
    parser.add_argument("--profile", choices=list(PROFILES), default=DEFAULT_PROFILE_NAME)
    parser.add_argument("--mode", choices=["sequential", "fountain"], default=DEFAULT_MODE)
    parser.add_argument("--bpc", type=int, choices=[1, 2, 3], default=DEFAULT_BITS_PER_CHANNEL,
                        help=f"Bits per color channel (default: {DEFAULT_BITS_PER_CHANNEL})")
    parser.add_argument("--size", type=_positive_int, default=100,
                        help="Payload size in KiB (default: 100)")
    parser.add_argument("--duration", type=_positive_float, default=10.0,
                        help="Transfer deadline in seconds, excluding warm-up (default: 10)")
    parser.add_argument("--no-json", action="store_true",
                        help="Print human-readable output instead of JSON")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    profile = replace(PROFILES[args.profile], bits_per_channel=args.bpc)
    sys.stderr.write(
        f"In-memory {args.mode} benchmark: {args.profile}, {args.bpc} bpc, "
        f"{args.size} KiB payload; warming up before measurement...\n"
    )
    try:
        result = run_benchmark(profile, args.mode, args.size, args.duration)
    except ValueError as exc:
        parser.error(str(exc))
    if args.no_json:
        print(f"Profile:       {result.profile}")
        print(f"Mode:          {result.mode}")
        print(f"Frames/sec:    {result.frames_per_sec:.2f}")
        print(f"Bytes/sec:     {result.bytes_per_sec:.2f}")
        print(f"Overhead:      {result.overhead_pct:.2f}%")
        print(f"Error rate:    {result.error_rate:.6f}")
        print(f"Duration:      {result.duration_sec:.6f}s")
        print(f"Warm-up:       {result.warmup_duration_sec:.6f}s (excluded)")
        print(f"Total frames:  {result.total_frames}")
        print(f"Useful bytes:  {result.total_bytes} / {result.payload_bytes}")
        print(f"Completed:     {result.completed}")
        print(f"Integrity OK:  {result.integrity_ok}")
        print(f"Timed out:     {result.timed_out}")
    else:
        print(result.to_json())
    if not result.completed or not result.integrity_ok or result.timed_out:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
