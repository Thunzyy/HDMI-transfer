"""Unit tests for ResolutionProfile, PROFILES, and protocol profile injection.

Validates:
- Derived spatial values for each named preset (speed, balanced, quality)
- Frozen immutability of profile instances
- DEFAULT_PROFILE identity
- Backward compatibility of module-level config constants
- Protocol classes accept and respect optional profile parameter
- Encode/decode roundtrip with profile injection
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from hdmi_transfer.config import (
    BLOCKS_PER_FRAME,
    BYTES_PER_FRAME,
    COLS,
    DEFAULT_PROFILE,
    HEIGHT,
    PROFILES,
    ROWS,
    ResolutionProfile,
    WIDTH,
)
from hdmi_transfer.protocols.fountain import FountainProtocol
from hdmi_transfer.protocols.sequential import SequentialProtocol


# ---------------------------------------------------------------------------
# Profile math tests
# ---------------------------------------------------------------------------


class TestSpeedProfile:
    """Verify speed profile (1920x1080, block_size=8, 240fps)."""

    @pytest.fixture()
    def profile(self) -> ResolutionProfile:
        return PROFILES["speed"]

    def test_cols(self, profile: ResolutionProfile) -> None:
        assert profile.cols == 240

    def test_rows(self, profile: ResolutionProfile) -> None:
        assert profile.rows == 135

    def test_blocks_per_frame(self, profile: ResolutionProfile) -> None:
        assert profile.blocks_per_frame == 32400

    def test_bits_per_frame(self, profile: ResolutionProfile) -> None:
        assert profile.bits_per_frame == 97200

    def test_seq_bytes_per_frame(self, profile: ResolutionProfile) -> None:
        assert profile.seq_bytes_per_frame == 12133

    def test_fount_bytes_per_frame(self, profile: ResolutionProfile) -> None:
        assert profile.fount_bytes_per_frame == 12134


class TestBalancedProfile:
    """Balanced profile has same spatial params as speed, different fps."""

    def test_same_resolution_as_speed(self) -> None:
        speed = PROFILES["speed"]
        balanced = PROFILES["balanced"]
        assert balanced.cols == speed.cols
        assert balanced.rows == speed.rows
        assert balanced.blocks_per_frame == speed.blocks_per_frame
        assert balanced.seq_bytes_per_frame == speed.seq_bytes_per_frame
        assert balanced.fount_bytes_per_frame == speed.fount_bytes_per_frame

    def test_different_target_fps(self) -> None:
        assert PROFILES["balanced"].target_fps == 60
        assert PROFILES["speed"].target_fps == 240


class TestQualityProfile:
    """Verify quality profile (3840x2160, block_size=8, 30fps)."""

    @pytest.fixture()
    def profile(self) -> ResolutionProfile:
        return PROFILES["quality"]

    def test_cols(self, profile: ResolutionProfile) -> None:
        assert profile.cols == 480

    def test_rows(self, profile: ResolutionProfile) -> None:
        assert profile.rows == 270

    def test_blocks_per_frame(self, profile: ResolutionProfile) -> None:
        assert profile.blocks_per_frame == 129600

    def test_seq_bytes_per_frame(self, profile: ResolutionProfile) -> None:
        assert profile.seq_bytes_per_frame == 48583

    def test_fount_bytes_per_frame(self, profile: ResolutionProfile) -> None:
        assert profile.fount_bytes_per_frame == 48584


# ---------------------------------------------------------------------------
# Immutability and identity
# ---------------------------------------------------------------------------


def test_profiles_are_frozen() -> None:
    """Attempting to set a field on a frozen profile raises an error."""
    profile = PROFILES["speed"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.width = 1234  # type: ignore[misc]


def test_default_profile_is_speed() -> None:
    """DEFAULT_PROFILE must be the speed preset."""
    assert DEFAULT_PROFILE is PROFILES["speed"]


# ---------------------------------------------------------------------------
# Protocol injection tests
# ---------------------------------------------------------------------------


def test_sequential_protocol_default_compat() -> None:
    """SequentialProtocol() with no args matches legacy bytes_per_frame."""
    proto = SequentialProtocol()
    assert proto.bytes_per_frame == 12133


def test_sequential_protocol_with_quality_profile() -> None:
    """SequentialProtocol(profile=quality) uses 4K payload capacity."""
    proto = SequentialProtocol(profile=PROFILES["quality"])
    assert proto.bytes_per_frame == 48583


def test_fountain_protocol_default_compat() -> None:
    """FountainProtocol() with no args matches legacy bytes_per_frame."""
    proto = FountainProtocol()
    assert proto.bytes_per_frame == 12134


def test_fountain_protocol_with_quality_profile() -> None:
    """FountainProtocol(profile=quality) uses 4K payload capacity."""
    proto = FountainProtocol(profile=PROFILES["quality"])
    assert proto.bytes_per_frame == 48584


# ---------------------------------------------------------------------------
# Encode / decode roundtrip
# ---------------------------------------------------------------------------


def test_encode_decode_roundtrip_with_profile() -> None:
    """Full encode -> sample -> decode roundtrip with speed profile."""
    profile = PROFILES["speed"]
    proto = SequentialProtocol(profile=profile)

    payload = bytes(range(256)) * 10  # 2560 bytes < 12133
    frame = proto.encode_frame(payload, frame_index=0, total_frames=1)

    # Frame should be (height, width, 3) uint8
    assert frame.shape == (profile.height, profile.width, 3)
    assert frame.dtype == np.uint8

    # Sample block centres to reconstruct the (ROWS, COLS, 3) grid
    block = profile.block_size
    half = block // 2
    sampled = frame[half::block, half::block, :]
    assert sampled.shape == (profile.rows, profile.cols, 3)

    result = proto.decode_frame(sampled)
    assert result.is_valid
    assert result.data == payload


# ---------------------------------------------------------------------------
# Backward compatibility of module-level constants
# ---------------------------------------------------------------------------


def test_backward_compat_module_constants() -> None:
    """Module-level WIDTH/HEIGHT/COLS/ROWS/BYTES_PER_FRAME remain unchanged."""
    assert WIDTH == 1920
    assert HEIGHT == 1080
    assert COLS == 240
    assert ROWS == 135
    assert BYTES_PER_FRAME == 12133
    assert BLOCKS_PER_FRAME == 32400
