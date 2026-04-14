"""Compatibility shim for the legacy web server import path."""

from hdmi_exfil.interfaces.web import create_app

__all__ = ["create_app"]
