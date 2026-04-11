"""Backward-compatible import shim -- canonical location: hdmi_exfil.interfaces.cli.receiver_console."""

from hdmi_exfil.compat.imports import reexport

reexport(globals(), "hdmi_exfil.interfaces.cli.receiver_console")
