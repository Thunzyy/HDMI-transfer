"""Backward-compatible import shim -- canonical location: hdmi_exfil.core.file_handling.metadata."""

from hdmi_exfil.compat.imports import reexport

reexport(globals(), "hdmi_exfil.core.file_handling.metadata")
