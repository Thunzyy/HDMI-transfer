"""Backward-compatible import shim -- canonical location: hdmi_exfil.core.file_handling."""

from hdmi_exfil.compat.imports import reexport

reexport(globals(), "hdmi_exfil.core.file_handling")
