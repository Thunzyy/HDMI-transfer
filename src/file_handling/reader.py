"""Backward-compatible import shim -- canonical location: hdmi_transfer.core.file_handling.reader."""

from hdmi_transfer.compat.imports import reexport

reexport(globals(), "hdmi_transfer.core.file_handling.reader")
