"""Shared HDMI preflight helpers used by the web sender and receiver."""

from __future__ import annotations

from functools import lru_cache

from hdmi_exfil.core.config import FRAME_TYPE_START
from hdmi_exfil.core.file_handling.metadata import build_start_metadata, parse_start_metadata
from hdmi_exfil.core.protocols.base import FrameResult

PREFLIGHT_FILENAME = "__hdmi_preflight__.bin"
PREFLIGHT_FILE_BYTES = b"HDMI_EXFIL_PREFLIGHT_V1"
PREFLIGHT_TOTAL_FRAMES = 1
PREFLIGHT_BITS_PER_CHANNEL = 1
PREFLIGHT_TIMEOUT_MS = 15_000
PREFLIGHT_POLL_INTERVAL_MS = 300
PREFLIGHT_SETTLE_MS = 200
PREFLIGHT_TRANSFER_CANDIDATE_TIMEOUT_MS = 4_000
PREFLIGHT_FILLER_BYTES = bytes(
    (((index * 73) + 19) ^ (index * 29)) & 0xFF
    for index in range(256)
)


@lru_cache(maxsize=1)
def build_preflight_start_payload() -> bytes:
    """Build the canonical sequential START payload for HDMI preflight."""
    return build_start_metadata(PREFLIGHT_FILENAME, PREFLIGHT_FILE_BYTES)


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
