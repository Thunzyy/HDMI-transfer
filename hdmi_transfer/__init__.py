"""Local import shim for the hdmi_transfer package when running from the repo."""

from __future__ import annotations

from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src"

__path__ = [str(_SOURCE_ROOT)]
__version__ = "0.1.0"
