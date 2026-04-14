"""Backward-compatible import shim -- canonical location: hdmi_exfil.sender.display.renderer."""

from hdmi_exfil.compat.imports import reexport

reexport(globals(), "hdmi_exfil.sender.display.renderer")
