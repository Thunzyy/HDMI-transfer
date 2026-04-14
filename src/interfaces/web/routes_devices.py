"""Device and profile HTTP routes."""

from __future__ import annotations

import logging

from flask import Flask, jsonify, request

from hdmi_exfil.adapters.capture.device_registry import resolve_device_open_target
from hdmi_exfil.core.config import PROFILES

log = logging.getLogger(__name__)


def _should_prime_persistent_capture(open_device: int | str, backend: int | None) -> bool:
    return not isinstance(open_device, str)


def register_device_routes(app: Flask) -> None:
    @app.route("/api/devices")
    def api_devices():
        force = request.args.get("force", "0") == "1"
        cached_only = request.args.get("cached_only", "0") == "1"
        log.info("[pcap] /api/devices called (force=%s cached_only=%s)", force, cached_only)

        cached_devices = app._device_registry.list_devices()
        if cached_devices and (cached_only or not force):
            log.info(
                "[pcap] /api/devices returning %d cached devices",
                len(cached_devices),
            )
            return jsonify(cached_devices)
        if cached_only:
            log.info("[pcap] /api/devices cached_only requested and cache empty")
            return jsonify([])

        log.info("[pcap] /api/devices: releasing persistent for detection")
        app._capture_manager.release()
        devices = app._detect_and_cache()

        if devices:
            import cv2

            device = devices[0]
            open_device, backend = resolve_device_open_target(device)
            if _should_prime_persistent_capture(open_device, backend):
                app._capture_manager.prime(
                    device=device["index"],
                    open_device=open_device,
                    backend=int(backend or cv2.CAP_MSMF),
                )
        return jsonify(devices)

    @app.route("/api/devices/warm", methods=["POST"])
    def api_warm_device():
        data = request.get_json(force=True)
        device_idx = int(data.get("device", 0))
        log.info("[pcap] /api/devices/warm called: device=%d", device_idx)

        if app._capture_manager.is_primed(device=device_idx):
            log.info(
                "[pcap] /api/devices/warm: already open for device %d",
                device_idx,
            )
            return jsonify({"status": "already_open"})

        device = app._device_registry.get_device(device_idx)
        if device is None:
            return jsonify({"status": "unknown_device"}), 400
        open_device, backend = resolve_device_open_target(device)
        if not _should_prime_persistent_capture(open_device, backend):
            return jsonify({"status": "skipped"})

        app._capture_manager.prime_async(
            device=device_idx,
            open_device=open_device,
            backend=int(backend or 0),
        )
        return jsonify({"status": "opening"})

    @app.route("/api/profiles")
    def api_profiles():
        profiles = {}
        for name, profile in PROFILES.items():
            profiles[name] = {
                "name": profile.name,
                "width": profile.width,
                "height": profile.height,
                "block_size": profile.block_size,
                "target_fps": profile.target_fps,
                "fount_bytes_per_frame": profile.fount_bytes_per_frame,
            }
        return jsonify(profiles)
