"""File / directory reading with zip packaging.

Reads a file (or zips a directory) and returns the basename + raw bytes,
ready for protocol encoding.

Usage::

    from hdmi_exfil.file_handling.reader import read_input

    name, data = read_input("/path/to/file_or_dir")
"""

from __future__ import annotations

import os
import shutil


def read_input(filepath: str) -> tuple[str, bytes]:
    """Read a file or directory for transmission.

    If *filepath* is a directory it is first archived to a zip file
    (same approach as the original ``sender.py``).

    Parameters
    ----------
    filepath:
        Path to the file or directory to read.

    Returns
    -------
    tuple[str, bytes]
        ``(basename, file_content)`` where *basename* is the leaf
        filename (e.g. ``"data.zip"``) and *file_content* is the raw
        bytes.

    Raises
    ------
    FileNotFoundError
        If *filepath* does not exist.
    """
    if os.path.isdir(filepath):
        base_name = os.path.basename(os.path.normpath(filepath))
        archive_path = shutil.make_archive(base_name, "zip", filepath)
        filepath = archive_path

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(filepath, "rb") as f:
        content = f.read()

    return os.path.basename(filepath), content
