"""Compatibility shim for the legacy web server import path."""

from hdmi_transfer.interfaces.web import create_app

__all__ = ["create_app"]
