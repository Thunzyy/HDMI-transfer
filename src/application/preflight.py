"""Shared HDMI preflight helpers used by the web sender and receiver."""

from __future__ import annotations

from functools import lru_cache
import struct
import zlib

import numpy as np

from hdmi_transfer.core.config import (
    FRAME_TYPE_START, HEADER_SIZE, SEQ_HEADER_FMT, SEQ_MAGIC, ResolutionProfile,
)
from hdmi_transfer.core.file_handling.metadata import build_start_metadata, parse_start_metadata
from hdmi_transfer.core.protocols.base import FrameResult
from hdmi_transfer.core.protocols.encoding import bytes_to_pixels, pixels_to_bytes

PREFLIGHT_FILENAME = "__hdmi_preflight__.bin"
PREFLIGHT_FILE_BYTES = b"HDMI_EXFIL_PREFLIGHT_V1"
PREFLIGHT_TOTAL_FRAMES = 1
PREFLIGHT_BITS_PER_CHANNEL = 1
PREFLIGHT_TIMEOUT_MS = 15_000
PREFLIGHT_POLL_INTERVAL_MS = 300
PREFLIGHT_SETTLE_MS = 200
PREFLIGHT_OFFLINE_INITIAL_MS = 3_000
PREFLIGHT_OFFLINE_RECHECK_MS = 1_000
PREFLIGHT_TRANSFER_CANDIDATE_TIMEOUT_MS = 4_000
PREFLIGHT_FILLER_BYTES = bytes(
    (((index * 73) + 19) ^ (index * 29)) & 0xFF
    for index in range(256)
)


@lru_cache(maxsize=1)
def build_preflight_start_payload() -> bytes:
    """Build the canonical sequential START payload for HDMI preflight."""
    return build_start_metadata(PREFLIGHT_FILENAME, PREFLIGHT_FILE_BYTES)


def build_calibration_payload(payload_capacity: int) -> bytes:
    """Cover the sampled color pattern with the sequential frame CRC.

    The metadata prefix stays compatible with legacy preflight readers. The
    sequential payload length is a uint16, including on larger video profiles.
    """
    prefix = build_preflight_start_payload()
    size = min(int(payload_capacity), 65535)
    if size < len(prefix):
        raise ValueError("Profile is too small for the calibration metadata")
    remaining = size - len(prefix)
    filler = (PREFLIGHT_FILLER_BYTES * ((remaining + 255) // 256))[:remaining]
    return prefix + filler


def _calibration_frame_bytes(profile: ResolutionProfile, frame_index: int) -> bytes:
    """Canonical sequential frame plus the pattern beyond its uint16 payload."""
    payload = build_calibration_payload(profile.seq_bytes_per_frame)
    header = struct.pack(
        SEQ_HEADER_FMT, SEQ_MAGIC, FRAME_TYPE_START, frame_index,
        PREFLIGHT_TOTAL_FRAMES, len(payload),
    )
    crc = struct.pack(">I", zlib.crc32(header + payload) & 0xFFFFFFFF)
    capacity = profile.rows * profile.cols * 3 * profile.bits_per_channel // 8
    encoded = bytearray(capacity)
    prefix = header + crc + payload
    encoded[:len(prefix)] = prefix
    # The browser restarts its filler pattern at the first byte beyond payload.
    apply_preflight_visual_filler(encoded, used_prefix_len=len(prefix))
    return bytes(encoded)


def build_calibration_frame(profile: ResolutionProfile, frame_index: int) -> np.ndarray:
    """Render the same full-surface calibration pattern as the browser sender."""
    grid = bytes_to_pixels(
        _calibration_frame_bytes(profile, frame_index), profile.blocks_per_frame,
        profile.rows, profile.cols, profile.bits_per_channel,
    )
    frame = np.repeat(np.repeat(grid, profile.block_size, axis=0), profile.block_size, axis=1)
    return frame[:profile.height, :profile.width, ::-1]


def is_calibration_frame_valid(
    sampled_bgr: np.ndarray, profile: ResolutionProfile, result: FrameResult | None,
) -> bool:
    """Check the complete sampled pattern, including the tail beyond CRC.

    A sequential CRC only covers at most 65535 payload bytes. Large profiles
    have additional symbols; comparing their known pattern is essential to
    avoid accepting a correct header with a corrupted lower image. Legacy
    metadata-only preflight frames remain recognisable, but cannot validate
    this full-surface calibration or populate its persistent cache.
    """
    if not is_preflight_start_result(result) or result.frame_index is None:
        return False
    if sampled_bgr.shape != (profile.rows, profile.cols, 3):
        return False
    expected = _calibration_frame_bytes(profile, result.frame_index)
    if result.data != expected[HEADER_SIZE:HEADER_SIZE + min(profile.seq_bytes_per_frame, 65535)]:
        return False
    actual = pixels_to_bytes(sampled_bgr[..., ::-1], profile.bits_per_channel)
    return actual[:len(expected)] == expected


@lru_cache(maxsize=1)
def _expected_preflight_metadata() -> tuple[int, bytes, str]:
    payload = build_preflight_start_payload()
    file_size, sha256_hash, filename = parse_start_metadata(payload)
    assert file_size is not None
    assert sha256_hash is not None
    assert filename is not None
    return file_size, sha256_hash, filename


def is_preflight_start_payload(payload: bytes | bytearray | None) -> bool:
    """Return True when *payload* matches the canonical preflight metadata."""
    if payload is None:
        return False
    file_size, sha256_hash, filename = parse_start_metadata(payload)
    if file_size is None or sha256_hash is None or filename is None:
        return False
    expected_size, expected_sha256, expected_name = _expected_preflight_metadata()
    return (
        file_size == expected_size
        and bytes(sha256_hash) == expected_sha256
        and filename == expected_name
    )


def is_preflight_start_result(result: FrameResult | None) -> bool:
    """Return True when *result* is the canonical sequential preflight START."""
    if result is None or not result.is_valid or result.frame_type != FRAME_TYPE_START:
        return False
    return is_preflight_start_payload(result.data)


def apply_preflight_visual_filler(
    frame_bytes: bytearray,
    *,
    used_prefix_len: int,
) -> bytearray:
    """Fill the unused tail of a preflight frame with a dense visual pattern.

    The sequential decoder only consumes the leading header + payload bytes
    announced by ``payload_len``. This helper keeps that canonical prefix
    untouched and fills the remainder with a deterministic high-contrast
    pattern so HDMI capture and geometry alignment have more signal.
    """
    start = max(0, int(used_prefix_len))
    if start >= len(frame_bytes):
        return frame_bytes

    pattern = PREFLIGHT_FILLER_BYTES
    write_offset = start
    while write_offset < len(frame_bytes):
        remaining = len(frame_bytes) - write_offset
        chunk = pattern[:remaining]
        frame_bytes[write_offset : write_offset + len(chunk)] = chunk
        write_offset += len(chunk)
    return frame_bytes
