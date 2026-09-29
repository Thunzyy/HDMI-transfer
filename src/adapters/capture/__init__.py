"""Capture adapters used by CLI and web interfaces."""

from hdmi_transfer.adapters.capture.capture_manager import CaptureManager
from hdmi_transfer.adapters.capture.device_registry import (
    DeviceRegistry,
    detect_devices,
    list_device_open_targets,
)
from hdmi_transfer.adapters.capture.resolver import (
    ResolvedCaptureTarget,
    resolve_capture_target,
    resolve_saved_capture_target,
)
from hdmi_transfer.core.capture.threaded import FPSReporter, ThreadedCapture

__all__ = [
    "CaptureManager",
    "DeviceRegistry",
    "FPSReporter",
    "ResolvedCaptureTarget",
    "ThreadedCapture",
    "detect_devices",
    "list_device_open_targets",
    "resolve_capture_target",
    "resolve_saved_capture_target",
]
