"""Backward-compatible import shim -- canonical location: hdmi_transfer.sender.display."""

from hdmi_transfer.compat.imports import reexport

reexport(globals(), "hdmi_transfer.sender.display")
