"""Backward-compatible import shim -- canonical location: hdmi_exfil.interfaces.cli.calibrate."""

from hdmi_exfil.compat.imports import reexport

reexport(globals(), "hdmi_exfil.interfaces.cli.calibrate")
