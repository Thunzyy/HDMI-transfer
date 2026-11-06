"""File / directory reading with zip packaging.

Reads a file (or zips a directory) and returns the basename + raw bytes,
ready for protocol encoding.

Usage::

    from hdmi_transfer.core.file_handling.reader import read_input

    name, data = read_input("/path/to/file_or_dir")
"""

from __future__ import annotations

import io
import os
import zipfile


def _zip_directory(dirpath: str) -> tuple[str, bytes]:
    """Zip *dirpath* in memory; entries are prefixed with the folder name."""
    root = os.path.normpath(dirpath)
    base_name = os.path.basename(root)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for current, dirs, files in os.walk(root):
            dirs.sort()
            rel = os.path.relpath(current, os.path.dirname(root))
            if current != root:
                archive.write(current, rel)
            for name in sorted(files):
                archive.write(os.path.join(current, name), os.path.join(rel, name))
    return f"{base_name}.zip", buffer.getvalue()


def read_input(filepath: str) -> tuple[str, bytes]:
    """Read a file or directory for transmission.

    If *filepath* is a directory it is zipped in memory and sent as
    ``<folder>.zip``.

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
        return _zip_directory(filepath)

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(filepath, "rb") as f:
        content = f.read()

    return os.path.basename(filepath), content
