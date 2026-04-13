"""Shared capture-source resolution for CLI and other non-web entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2

from hdmi_exfil.adapters.capture.device_registry import (
    detect_devices,
    list_device_open_targets,
    resolve_device_open_target,
)


DeviceDetector = Callable[[], list[dict]]


@dataclass(frozen=True)
class ResolvedCaptureTarget:
    """Concrete capture target after logical/raw source resolution."""

    requested_source: int | str
    open_source: int | str
    backend: int | None = None
    logical_index: int | None = None
    device_name: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    matched_by: str = "raw"
    auto_fixed: bool = False
    forced_raw: bool = False
    fallback_targets: tuple[tuple[int, int | None], ...] = ()

    def describe(self) -> str:
        """Return a short human-readable description of the resolved target."""
        if isinstance(self.open_source, str) and self.backend is None:
            return f"Using file source: {self.open_source}"

        if self.device_name is None:
            label = f"Using raw capture source: {self.open_source}"
            if self.backend is not None:
                label += f" via {_backend_name(self.backend)}"
            return label

        details: list[str] = [self.device_name]
        if self.width and self.height:
            fps = f" @ {self.fps:.0f} FPS" if self.fps else ""
            details.append(f"{self.width}x{self.height}{fps}")
        if self.logical_index is not None:
            details.append(f"logical {self.logical_index}")
        details.append(
            f"open {self.open_source}"
            + (
                f" via {_backend_name(self.backend)}"
                if self.backend is not None
                else ""
            ),
        )

        prefix = "Auto-fixed capture target" if self.auto_fixed else "Using capture target"
        return f"{prefix}: " + " | ".join(details)


def resolve_capture_target(
    source: int | str,
    *,
    detector: DeviceDetector = detect_devices,
) -> ResolvedCaptureTarget:
    """Resolve a CLI capture source into a concrete backend/open index.

    Supported selectors:
    - ``0`` or ``\"0\"``: logical capture index from device detection
    - ``raw:1``: force raw OpenCV index ``1``
    - ``name:Elgato``: pick the detected device by exact/substr name
    - file path / URL-like string: passed through unchanged
    """
    if isinstance(source, str):
        raw_value = source.strip()
        lowered = raw_value.casefold()

        if lowered.startswith("raw:"):
            forced = raw_value.split(":", 1)[1].strip()
            if forced.isdigit():
                return ResolvedCaptureTarget(
                    requested_source=source,
                    open_source=int(forced),
                    forced_raw=True,
                )
            return ResolvedCaptureTarget(
                requested_source=source,
                open_source=forced,
                forced_raw=True,
            )

        if lowered.startswith("name:"):
            query = raw_value.split(":", 1)[1].strip()
            devices = detector()
            device = _find_device_by_name(devices, query)
            if device is None:
                raise RuntimeError(f"Capture device not found: {query}")
            return _resolved_from_device(
                requested_source=source,
                device=device,
                matched_by="name",
                auto_fixed=True,
            )

        if raw_value.isdigit():
            source = int(raw_value)
        else:
            return ResolvedCaptureTarget(
                requested_source=source,
                open_source=source,
            )

    devices = detector()
    device = _find_device_by_logical_index(devices, int(source))
    if device is not None:
        open_source, backend = _preferred_open_target(device)
        return _resolved_from_device(
            requested_source=source,
            device=device,
            matched_by="logical_index",
            auto_fixed=(open_source != int(source)),
        )

    device = _find_device_by_raw_dshow_index(devices, int(source))
    if device is not None:
        return ResolvedCaptureTarget(
            requested_source=source,
            open_source=int(source),
            backend=int(cv2.CAP_DSHOW),
            logical_index=int(device["index"]),
            device_name=str(device["name"]),
            width=_maybe_int(device.get("width")),
            height=_maybe_int(device.get("height")),
            fps=_maybe_float(device.get("fps")),
            matched_by="raw_dshow_index",
        )

    return ResolvedCaptureTarget(
        requested_source=source,
        open_source=int(source),
    )


def resolve_saved_capture_target(
    *,
    saved_name: str,
    saved_index: int | None,
    detector: DeviceDetector = detect_devices,
) -> ResolvedCaptureTarget:
    """Resolve a saved capture target by stable name, auto-healing index drift."""
    devices = detector()
    device = _find_device_by_name(devices, saved_name)
    if device is None:
        if saved_index is None:
            raise RuntimeError(f"Capture device not found: {saved_name}")
        return resolve_capture_target(saved_index, detector=lambda: devices)

    requested = saved_index if saved_index is not None else f"name:{saved_name}"
    auto_fixed = saved_index is None or int(device["index"]) != int(saved_index)
    return _resolved_from_device(
        requested_source=requested,
        device=device,
        matched_by="saved_name",
        auto_fixed=auto_fixed or _preferred_open_target(device)[0] != int(device["index"]),
    )


def _resolved_from_device(
    *,
    requested_source: int | str,
    device: dict,
    matched_by: str,
    auto_fixed: bool,
) -> ResolvedCaptureTarget:
    targets = list_device_open_targets(device)
    open_source, backend = targets[0]
    return ResolvedCaptureTarget(
        requested_source=requested_source,
        open_source=open_source,
        backend=backend,
        logical_index=int(device["index"]),
        device_name=str(device["name"]),
        width=_maybe_int(device.get("width")),
        height=_maybe_int(device.get("height")),
        fps=_maybe_float(device.get("fps")),
        matched_by=matched_by,
        auto_fixed=auto_fixed,
        fallback_targets=tuple(targets[1:]),
    )


def _preferred_open_target(device: dict) -> tuple[int, int | None]:
    return resolve_device_open_target(device)


def _find_device_by_logical_index(devices: list[dict], logical_index: int) -> dict | None:
    for device in devices:
        if int(device["index"]) == logical_index:
            return device
    return None


def _find_device_by_raw_dshow_index(devices: list[dict], raw_index: int) -> dict | None:
    for device in devices:
        if device.get("prefer_dshow") and device.get("dshow_index") == raw_index:
            return device
    return None


def _find_device_by_name(devices: list[dict], query: str) -> dict | None:
    needle = _normalize_name(query)
    if not needle:
        return None

    for device in devices:
        if _normalize_name(str(device["name"])) == needle:
            return device

    for device in devices:
        if needle in _normalize_name(str(device["name"])):
            return device

    return None


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _backend_name(backend: int | None) -> str:
    if backend == cv2.CAP_DSHOW:
        return "DSHOW"
    if backend == cv2.CAP_MSMF:
        return "MSMF"
    if backend == cv2.CAP_ANY:
        return "AUTO"
    return str(backend)


def _maybe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
