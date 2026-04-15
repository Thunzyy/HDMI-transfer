"""Tests for calibration test patterns and benchmark result serialization.

Covers:
- Checkerboard pattern generation (shape, values, alternation)
- SNR computation (perfect capture and noisy capture)
- BenchmarkResult JSON serialization
- Sequential roundtrip benchmark execution
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from hdmi_transfer.config import PROFILES


# ---------------------------------------------------------------------------
# Checkerboard pattern tests
# ---------------------------------------------------------------------------


def test_checkerboard_shape() -> None:
    """generate_checkerboard returns correct shape for speed profile."""
    from hdmi_transfer.display.test_patterns import generate_checkerboard

    profile = PROFILES["speed"]
    frame = generate_checkerboard(profile)

    assert frame.shape == (profile.height, profile.width, 3)
    assert frame.dtype == np.uint8


def test_checkerboard_shape_quality() -> None:
    """generate_checkerboard returns correct shape for quality (4K) profile."""
    from hdmi_transfer.display.test_patterns import generate_checkerboard

    profile = PROFILES["quality"]
    frame = generate_checkerboard(profile)

    assert frame.shape == (profile.height, profile.width, 3)
    assert frame.dtype == np.uint8


def test_checkerboard_pattern() -> None:
    """Verify alternating blocks: (0,0) is white, (0,1) is black."""
    from hdmi_transfer.display.test_patterns import generate_checkerboard

    profile = PROFILES["speed"]
    frame = generate_checkerboard(profile)
    bs = profile.block_size
    half = bs // 2

    # Block (0, 0) centre should be white
    centre_00 = frame[half, half]
    assert tuple(centre_00) == (255, 255, 255), f"Block (0,0) = {centre_00}"

    # Block (0, 1) centre should be black
    centre_01 = frame[half, bs + half]
    assert tuple(centre_01) == (0, 0, 0), f"Block (0,1) = {centre_01}"

    # Block (1, 0) centre should be black
    centre_10 = frame[bs + half, half]
    assert tuple(centre_10) == (0, 0, 0), f"Block (1,0) = {centre_10}"

    # Block (1, 1) centre should be white
    centre_11 = frame[bs + half, bs + half]
    assert tuple(centre_11) == (255, 255, 255), f"Block (1,1) = {centre_11}"


def test_checkerboard_only_bw() -> None:
    """All pixel values in the checkerboard are either 0 or 255."""
    from hdmi_transfer.display.test_patterns import generate_checkerboard

    profile = PROFILES["speed"]
    frame = generate_checkerboard(profile)

    unique_values = np.unique(frame)
    assert set(unique_values) == {0, 255}, f"Unexpected values: {unique_values}"


# ---------------------------------------------------------------------------
# SNR computation tests
# ---------------------------------------------------------------------------


def test_snr_perfect_capture() -> None:
    """compute_snr with frame == expected returns 60.0 (perfect)."""
    from hdmi_transfer.display.test_patterns import compute_snr, generate_checkerboard

    profile = PROFILES["speed"]
    frame = generate_checkerboard(profile)

    snr = compute_snr(frame, frame, profile.block_size)
    assert snr == pytest.approx(60.0)


def test_snr_with_noise() -> None:
    """Adding gaussian noise should decrease SNR but keep it positive."""
    from hdmi_transfer.display.test_patterns import compute_snr, generate_checkerboard

    profile = PROFILES["speed"]
    expected = generate_checkerboard(profile)

    # Add moderate noise
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 30, expected.shape).astype(np.float64)
    noisy = np.clip(expected.astype(np.float64) + noise, 0, 255).astype(np.uint8)

    snr = compute_snr(noisy, expected, profile.block_size)

    # SNR should be positive but significantly lower than 60 dB
    assert snr > 0.0
    assert snr < 50.0


def test_snr_heavy_noise() -> None:
    """Very heavy noise should produce low SNR."""
    from hdmi_transfer.display.test_patterns import compute_snr, generate_checkerboard

    profile = PROFILES["speed"]
    expected = generate_checkerboard(profile)

    # Add heavy noise (std=80)
    rng = np.random.default_rng(123)
    noise = rng.normal(0, 80, expected.shape)
    noisy = np.clip(expected.astype(np.float64) + noise, 0, 255).astype(np.uint8)

    snr = compute_snr(noisy, expected, profile.block_size)

    # Should be much lower
    assert snr < 30.0


# ---------------------------------------------------------------------------
# BenchmarkResult tests
# ---------------------------------------------------------------------------


def test_benchmark_result_json() -> None:
    """BenchmarkResult.to_json() produces valid JSON with all expected keys."""
    from hdmi_transfer.cli.benchmark import BenchmarkResult

    r = BenchmarkResult(
        profile="speed",
        mode="sequential",
        frames_per_sec=100.0,
        bytes_per_sec=1213300.0,
        overhead_pct=0.0,
        error_rate=0.0,
        duration_sec=1.0,
        total_frames=100,
        total_bytes=1213300,
    )

    data = json.loads(r.to_json())
    expected_keys = {
        "profile",
        "mode",
        "frames_per_sec",
        "bytes_per_sec",
        "overhead_pct",
        "error_rate",
        "duration_sec",
        "total_frames",
        "total_bytes",
    }
    assert set(data.keys()) == expected_keys
    assert data["profile"] == "speed"
    assert data["mode"] == "sequential"
    assert data["frames_per_sec"] == 100.0


def test_benchmark_result_json_roundtrip() -> None:
    """BenchmarkResult JSON values match constructor arguments exactly."""
    from hdmi_transfer.cli.benchmark import BenchmarkResult

    r = BenchmarkResult(
        profile="quality",
        mode="fountain",
        frames_per_sec=42.5,
        bytes_per_sec=500000.0,
        overhead_pct=5.3,
        error_rate=0.001,
        duration_sec=2.5,
        total_frames=106,
        total_bytes=1250000,
    )

    data = json.loads(r.to_json())
    assert data["profile"] == "quality"
    assert data["mode"] == "fountain"
    assert data["overhead_pct"] == 5.3
    assert data["error_rate"] == 0.001


# ---------------------------------------------------------------------------
# Sequential benchmark roundtrip
# ---------------------------------------------------------------------------


def test_benchmark_sequential_roundtrip() -> None:
    """run_benchmark with sequential mode completes with zero errors."""
    from hdmi_transfer.cli.benchmark import run_benchmark

    profile = PROFILES["speed"]
    result = run_benchmark(profile, "sequential", payload_size_kb=10, duration_sec=30)

    assert result.mode == "sequential"
    assert result.profile == "speed"
    assert result.frames_per_sec > 0
    assert result.error_rate == 0.0
    assert result.total_frames > 0
    assert result.total_bytes > 0
