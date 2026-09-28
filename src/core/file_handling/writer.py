"""Safe file writing with path sanitization and integrity verification.

Creates the output directory if needed, strips directory components from
filenames (preventing path-traversal attacks), and provides SHA-256
integrity checking.

Usage::

    from hdmi_transfer.core.file_handling.writer import write_output, verify_integrity

    path = write_output(data, "received.bin")
    ok = verify_integrity(data, expected_sha256)
"""

from __future__ import annotations

import hashlib
import os


def write_output(
    data: bytes,
    filename: str,
    output_dir: str = "received_files",
) -> str:
    """Write received data to disk with path sanitization.

    Parameters
    ----------
    data:
        Raw file content to save.
    filename:
        Desired filename (will be sanitized via ``os.path.basename``).
    output_dir:
        Directory to write into (created if missing).

    Returns
    -------
    str
        Absolute path to the saved file.
    """
    os.makedirs(output_dir, exist_ok=True)

    safe_name = os.path.basename(filename)
    save_path = os.path.join(output_dir, safe_name)

    with open(save_path, "wb") as f:
        f.write(data)

    return save_path


def verify_integrity(data: bytes, expected_sha256: bytes) -> bool:
    """Check whether *data* matches an expected SHA-256 digest.

    Parameters
    ----------
    data:
        Raw file content.
    expected_sha256:
        Expected 32-byte SHA-256 digest.

    Returns
    -------
    bool
        ``True`` if the computed digest matches *expected_sha256*.
    """
    return hashlib.sha256(data).digest() == expected_sha256
