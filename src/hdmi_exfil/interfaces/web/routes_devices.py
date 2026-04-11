"""Device and profile HTTP routes."""

from __future__ import annotations

import logging

from flask import Flask, jsonify, request

from hdmi_exfil.core.config import PROFILES

log = logging.getLogger(__name__)


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
            app._capture_manager.prime(
                device=device["index"],
                backend=device.get("backend", cv2.CAP_MSMF),
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

        backend = app._device_registry.get_backend(device_idx)
        if backend is None:
            return jsonify({"status": "unknown_device"}), 400

        app._capture_manager.prime_async(device=device_idx, backend=backend)
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
