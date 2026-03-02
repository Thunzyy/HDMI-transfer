"""CLI entry point for ``hdmi-bench`` -- automated throughput measurement.

Runs an in-memory encode/decode benchmark and outputs results as JSON.
No display or capture hardware required -- pure computational measurement.

Usage::

    hdmi-bench --profile speed --mode sequential --size 100
    hdmi-bench --profile quality --mode fountain --size 50 --duration 5
    hdmi-bench --no-json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass

import numpy as np

from hdmi_exfil.core.capture.sampler import sample_frame
from hdmi_exfil.core.config import DEFAULT_PROFILE, PROFILES, ResolutionProfile
from hdmi_exfil.core.protocols import get_protocol


@dataclass
class BenchmarkResult:
    """Structured benchmark measurement result."""

    profile: str
    mode: str  # "sequential" or "fountain"
    frames_per_sec: float
    bytes_per_sec: float
    overhead_pct: float  # fountain only, 0.0 for sequential
    error_rate: float
    duration_sec: float
    total_frames: int
    total_bytes: int

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), indent=2)


def run_benchmark(
    profile: ResolutionProfile,
    mode: str,
    payload_size_kb: int = 100,
    duration_sec: float = 10.0,
) -> BenchmarkResult:
    """Run an in-memory encode/decode throughput benchmark.

    Parameters
    ----------
    profile:
        Resolution profile to benchmark.
    mode:
        Protocol mode (``"sequential"`` or ``"fountain"``).
    payload_size_kb:
        Total payload size in kilobytes.
    duration_sec:
        Maximum benchmark duration in seconds (used for fountain mode timeout).

    Returns
    -------
    BenchmarkResult
        Benchmark metrics including throughput and error rate.
    """
    if mode == "sequential":
        return _bench_sequential(profile, payload_size_kb, duration_sec)
    elif mode == "fountain":
        return _bench_fountain(profile, payload_size_kb, duration_sec)
    else:
        raise ValueError(f"Unknown mode: {mode!r}")


def _bench_sequential(
    profile: ResolutionProfile,
    payload_size_kb: int,
    duration_sec: float,
) -> BenchmarkResult:
    """Benchmark sequential encode/decode roundtrip in memory."""
    proto = get_protocol("sequential", profile=profile)
    bpf = profile.seq_bytes_per_frame

    # Generate test payload
    payload = bytes(np.random.randint(0, 256, payload_size_kb * 1024, dtype=np.uint8))
    total_frames = math.ceil(len(payload) / bpf)

    errors = 0
    decoded_bytes = 0

    start = time.perf_counter()

    for i in range(total_frames):
        chunk_start = i * bpf
        chunk_end = min((i + 1) * bpf, len(payload))
        chunk = payload[chunk_start:chunk_end]

        # Encode
        frame_img = proto.encode_frame(chunk, i, total_frames)

        # Simulate capture: sample block centres (nearest-neighbour roundtrip)
        sampled = sample_frame(
            frame_img,
            profile.rows,
            profile.cols,
            profile.block_size,
        )

        # Decode
        result = proto.decode_frame(sampled)

        if result.is_valid and result.data is not None:
            decoded_bytes += len(result.data)
            if result.data != chunk:
                errors += 1
        else:
            errors += 1

    elapsed = time.perf_counter() - start

    fps = total_frames / elapsed if elapsed > 0 else 0.0
    bps = decoded_bytes / elapsed if elapsed > 0 else 0.0
    error_rate = errors / total_frames if total_frames > 0 else 0.0

    return BenchmarkResult(
        profile=profile.name,
        mode="sequential",
        frames_per_sec=round(fps, 2),
        bytes_per_sec=round(bps, 2),
        overhead_pct=0.0,
        error_rate=round(error_rate, 6),
        duration_sec=round(elapsed, 3),
        total_frames=total_frames,
        total_bytes=decoded_bytes,
    )


def _bench_fountain(
    profile: ResolutionProfile,
    payload_size_kb: int,
    duration_sec: float,
) -> BenchmarkResult:
    """Benchmark fountain encode/decode roundtrip in memory."""
    from hdmi_exfil.core.prng import choose_indices
    from hdmi_exfil.core.protocols.fountain import FountainDecoder
    from hdmi_exfil.core.protocols.xor_ops import xor_into

    proto = get_protocol("fountain", profile=profile)
    payload_per_frame = profile.fount_bytes_per_frame

    # Generate test payload
    raw_payload = bytes(
        np.random.randint(0, 256, payload_size_kb * 1024, dtype=np.uint8)
    )

    K = math.ceil(len(raw_payload) / payload_per_frame)
    if K < 1:
        K = 1

    # Slice into chunks as numpy arrays
    chunks: list[np.ndarray] = []
    for i in range(K):
        s = i * payload_per_frame
        e = min(s + payload_per_frame, len(raw_payload))
        chunk = np.zeros(payload_per_frame, dtype=np.uint8)
        chunk[: e - s] = np.frombuffer(raw_payload[s:e], dtype=np.uint8)
        chunks.append(chunk)

    # Decode side
    decoder = FountainDecoder(K, payload_per_frame)

    seed = 1
    frame_count = 0
    errors = 0
    decoded_bytes = 0

    start = time.perf_counter()

    while not decoder.is_complete():
        elapsed = time.perf_counter() - start
        if elapsed > duration_sec:
            break

        # Build droplet payload
        indices = choose_indices(seed, K)
        drop_payload = np.zeros(payload_per_frame, dtype=np.uint8)
        for idx in indices:
            xor_into(drop_payload, chunks[idx])

        # Encode
        frame_img = proto.encode_frame(
            drop_payload.tobytes(), frame_count, K, seed=seed,
        )

        # Simulate capture
        sampled = sample_frame(
            frame_img,
            profile.rows,
            profile.cols,
            profile.block_size,
        )

        # Decode frame
        result = proto.decode_frame(sampled)

        if result.is_valid and result.data is not None:
            decoder.add_droplet(
                result.frame_index, result.data,  # type: ignore[arg-type]
            )
        else:
            errors += 1

        seed = (seed + 1) & 0xFFFFFFFF
        if seed == 0:
            seed = 1
        frame_count += 1

    elapsed = time.perf_counter() - start

    if decoder.is_complete():
        file_data = decoder.get_file_data()
        decoded_bytes = len(file_data)

    fps = frame_count / elapsed if elapsed > 0 else 0.0
    bps = decoded_bytes / elapsed if elapsed > 0 else 0.0
    overhead_pct = (
        ((frame_count - K) / K) * 100.0 if K > 0 and decoder.is_complete() else 0.0
    )
    error_rate = errors / frame_count if frame_count > 0 else 0.0

    return BenchmarkResult(
        profile=profile.name,
        mode="fountain",
        frames_per_sec=round(fps, 2),
        bytes_per_sec=round(bps, 2),
        overhead_pct=round(overhead_pct, 2),
        error_rate=round(error_rate, 6),
        duration_sec=round(elapsed, 3),
        total_frames=frame_count,
        total_bytes=decoded_bytes,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hdmi-bench",
        description="HDMI Exfiltration Benchmark -- measure encode/decode throughput",
    )
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default="speed",
        help="Resolution profile (default: speed)",
    )
    parser.add_argument(
        "--mode",
        choices=["sequential", "fountain"],
        default="fountain",
        help="Encoding protocol to benchmark (default: fountain)",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=100,
        help="Payload size in KB (default: 100)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Max duration in seconds for fountain mode (default: 10)",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        default=False,
        help="Print human-readable output instead of JSON",
    )
    return parser


def main() -> None:
    """Entry point for ``hdmi-bench`` CLI command."""
    parser = _build_parser()
    args = parser.parse_args()

    profile = PROFILES.get(args.profile, DEFAULT_PROFILE)

    sys.stderr.write(
        f"Benchmarking {args.mode} mode with {args.profile} profile "
        f"({args.size} KB payload)...\n"
    )

    result = run_benchmark(
        profile=profile,
        mode=args.mode,
        payload_size_kb=args.size,
        duration_sec=args.duration,
    )

    if args.no_json:
        print(f"Profile:       {result.profile}")
        print(f"Mode:          {result.mode}")
        print(f"Frames/sec:    {result.frames_per_sec:.2f}")
        print(f"Bytes/sec:     {result.bytes_per_sec:.2f}")
        print(f"Overhead:      {result.overhead_pct:.2f}%")
        print(f"Error rate:    {result.error_rate:.6f}")
        print(f"Duration:      {result.duration_sec:.3f}s")
        print(f"Total frames:  {result.total_frames}")
        print(f"Total bytes:   {result.total_bytes}")
    else:
        print(result.to_json())


if __name__ == "__main__":
    main()
