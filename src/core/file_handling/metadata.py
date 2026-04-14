"""Metadata pack / unpack utilities for START frames and fountain transfers.

Extracted from sender.py (build), receiver.py (parse sequential), and
receiver_fountain.py (parse fountain).  Pure stdlib -- no dependency on
config or protocol modules.

Metadata layout (shared by both sequential START and fountain chunk-0):

    [4B file_size (>I)][32B SHA-256][2B name_len (>H)][NB filename (UTF-8)]

For fountain transfers the file content follows immediately after the
filename, so ``parse_fountain_metadata`` also returns *content_offset*.
"""

from __future__ import annotations

import hashlib
import struct


def build_start_metadata(filename: str, file_data: bytes) -> bytes:
    """Build a START-frame metadata payload.

    Layout: ``[4B file_size][32B SHA-256][2B filename_len][NB filename]``

    Parameters
    ----------
    filename:
        Original file name (will be UTF-8 encoded).
    file_data:
        Raw file content used to compute size and SHA-256 hash.

    Returns
    -------
    bytes
        Packed metadata ready to embed in a START frame payload.
    """
    sha256_hash = hashlib.sha256(file_data).digest()  # 32 bytes
    filename_bytes = filename.encode("utf-8")
    metadata = struct.pack(">I", len(file_data))  # 4B file_size
    metadata += sha256_hash  # 32B SHA-256
    metadata += struct.pack(">H", len(filename_bytes))  # 2B filename_len
    metadata += filename_bytes  # NB filename
    return metadata


def parse_start_metadata(
    payload: bytes | bytearray,
) -> tuple[int, bytes, str] | tuple[None, None, None]:
    """Parse sequential START-frame metadata.

    Returns
    -------
    tuple
        ``(file_size, sha256_hash, filename)`` on success, or
        ``(None, None, None)`` if the payload is too short or malformed.
    """
    if len(payload) < 38:  # 4 + 32 + 2 minimum
        return None, None, None
    try:
        file_size = struct.unpack(">I", payload[0:4])[0]
        sha256_hash = bytes(payload[4:36])
        name_len = struct.unpack(">H", payload[36:38])[0]
        if name_len > 1024 or 38 + name_len > len(payload):
            return None, None, None
        filename = payload[38 : 38 + name_len].decode("utf-8")
        return file_size, sha256_hash, filename
    except Exception:  # noqa: BLE001
        return None, None, None


def parse_fountain_metadata(
    full_data: bytes | bytearray,
) -> tuple[int, bytes, str, int] | tuple[None, None, None, None]:
    """Parse fountain transfer metadata prefix from reassembled data.

    Layout: ``[4B file_size][32B SHA-256][2B name_len][NB name][content...]``

    Returns
    -------
    tuple
        ``(file_size, sha256_hash, filename, content_offset)`` on success, or
        ``(None, None, None, None)`` if the data is too short or malformed.
    """
    if len(full_data) < 38:  # 4 + 32 + 2 minimum
        return None, None, None, None
    try:
        file_size = struct.unpack(">I", full_data[0:4])[0]
        sha256_hash = bytes(full_data[4:36])
        name_len = struct.unpack(">H", full_data[36:38])[0]
        if name_len > 1024 or 38 + name_len > len(full_data):
            return None, None, None, None
        filename = full_data[38 : 38 + name_len].decode("utf-8")
        content_offset = 38 + name_len
        return file_size, sha256_hash, filename, content_offset
    except Exception:  # noqa: BLE001
        return None, None, None, None
