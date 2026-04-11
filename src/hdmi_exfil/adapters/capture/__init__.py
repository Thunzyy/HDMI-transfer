"""Capture adapters used by CLI and web interfaces."""

from hdmi_exfil.adapters.capture.capture_manager import CaptureManager
from hdmi_exfil.adapters.capture.device_registry import DeviceRegistry, detect_devices
from hdmi_exfil.adapters.capture.threaded_capture import FPSReporter, ThreadedCapture

__all__ = [
    "CaptureManager",
    "DeviceRegistry",
    "FPSReporter",
    "ThreadedCapture",
    "detect_devices",
]
