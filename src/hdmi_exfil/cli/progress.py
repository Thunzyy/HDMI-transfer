"""Backward-compatible import shim -- canonical location: hdmi_exfil.core.cli.progress."""

from hdmi_exfil.compat.imports import reexport

reexport(globals(), "hdmi_exfil.core.cli.progress")
