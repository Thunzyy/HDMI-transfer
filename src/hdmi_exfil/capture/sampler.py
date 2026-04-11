"""Backward-compatible import shim -- canonical location: hdmi_exfil.core.capture.sampler."""

from hdmi_exfil.compat.imports import reexport

reexport(globals(), "hdmi_exfil.core.capture.sampler")
