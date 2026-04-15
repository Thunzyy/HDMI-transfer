"""Backward-compatible import shim -- canonical location: hdmi_transfer.interfaces.cli.receiver_console."""

from hdmi_transfer.compat.imports import reexport

reexport(globals(), "hdmi_transfer.interfaces.cli.receiver_console")
