"""Receiver HTTP routes."""

from __future__ import annotations

import json
import logging
import queue
import sys
from dataclasses import replace

from flask import Flask, Response, jsonify, request

from hdmi_exfil.adapters.capture.device_registry import (
    list_device_open_targets,
    resolve_device_open_target,
)
from hdmi_exfil.core.config import PROFILES

from .preview_stream import create_preview_response

log = logging.getLogger(__name__)


def register_receive_routes(app: Flask) -> None:
    @app.route("/api/receive/status")
    def api_receive_status():
        worker = app._receiver_worker
        if worker is not None and worker.is_alive():
            payload = {"active": True}
            try:
                payload.update(worker.get_preview_health())
            except Exception:
                pass
            return jsonify(payload)
        return jsonify({"active": False})

    @app.route("/api/receive/start", methods=["POST"])
    def api_receive_start():
        import cv2

        with app._receiver_control_lock:
            old_worker = app._receiver_worker
            if old_worker is not None and old_worker.is_alive():
                log.info("Auto-stopping previous worker before new START")
                old_worker.stop()
                app._receiver_worker = None

            data = request.get_json(force=True)
            device = int(data.get("device", 0))
            profile_name = data.get("profile", "speed")
            mode = data.get("mode", "auto")
            output = data.get("output", app.config["OUTPUT_DIR"])

            bpc = int(data.get("bpc", 1))
            if bpc not in (1, 2, 3):
                bpc = 1

            base_profile = PROFILES.get(profile_name)
            if base_profile is None:
                return jsonify({"error": f"Unknown profile: {profile_name}"}), 400

            profile = replace(base_profile, bits_per_channel=bpc)
            backend = app._device_registry.get_backend(device)
            device_info = app._device_registry.get_device(device)
            decode_device = device
            decode_backend = backend
            fallback_targets: list[tuple[int, int | None]] = []
            if device_info is not None:
                targets = list_device_open_targets(device_info)
                decode_device, decode_backend = targets[0]
                fallback_targets = targets[1:]
                if decode_device != device or decode_backend != backend:
                    log.info(
                        "[pcap] START: remapped capture target "
                        "(logical_index=%d -> open_index=%d, backend=%s)",
                        device,
                        decode_device,
                        decode_backend,
                    )
                if decode_backend == int(cv2.CAP_DSHOW):
                    app._capture_manager.release()

            if decode_backend is None:
                app._capture_manager.release()
                devices = app._detect_and_cache()
                for detected in devices:
                    if detected["index"] == device:
                        device_info = detected
                        break
                if device_info is not None:
                    targets = list_device_open_targets(device_info)
                    decode_device, decode_backend = targets[0]
                    fallback_targets = targets[1:]
                    if decode_backend == int(cv2.CAP_DSHOW):
                        app._capture_manager.release()

            precap = None
            on_cap_return = None
            if decode_backend != cv2.CAP_DSHOW:
                log.info("[pcap] START: waiting for persistent_ready (device=%d)...", device)
                ready = app._capture_manager.wait_until_ready(timeout=10.0)
                log.info("[pcap] START: persistent_ready=%s", ready)
                precap, _ = app._capture_manager.take(device=device)
                log.info("[pcap] START: precap=%s", "YES" if precap else "NO")
                on_cap_return = (
                    lambda raw_cap, decode_device=decode_device, decode_backend=decode_backend:
                    app._capture_manager.return_capture(
                        capture=raw_cap,
                        device=device,
                        open_device=decode_device,
                        backend=decode_backend,
                    )
                )

            from hdmi_exfil.web.receiver_worker import ReceiverWorker

            worker = ReceiverWorker(
                device=decode_device,
                profile=profile,
                mode=mode,
                output_dir=output,
                backend=decode_backend,
                precap=precap,
                on_cap_return=on_cap_return,
                fallback_targets=fallback_targets,
            )
            app._receiver_worker = worker
            worker.start()
            return jsonify({"status": "started"})

    @app.route("/api/receive/stop", methods=["POST"])
    def api_receive_stop():
        with app._receiver_control_lock:
            worker = app._receiver_worker
            if worker is None or not worker.is_alive():
                return jsonify({"error": "Not receiving"}), 409
            worker.stop()
            return jsonify({"status": "stopped"})

    @app.route("/api/receive/reset", methods=["POST"])
    def api_receive_reset():
        import cv2

        with app._receiver_control_lock:
            worker = app._receiver_worker
            if worker is not None and worker.is_alive():
                worker.stop()
            app._receiver_worker = None

            app._capture_manager.release()

            data = request.get_json(silent=True) or {}
            target_device = data.get("device")
            opened = False

            if target_device is not None:
                try:
                    target_device = int(target_device)
                except Exception:
                    target_device = None

            if isinstance(target_device, int):
                device_info = app._device_registry.get_device(target_device)
                backend = None
                open_device = target_device
                if device_info is not None:
                    open_device, backend = resolve_device_open_target(device_info)
                if backend is None:
                    devices = app._detect_and_cache()
                    for detected in devices:
                        if detected["index"] == target_device:
                            device_info = detected
                            open_device, backend = resolve_device_open_target(detected)
                            break
                if backend is not None:
                    app._capture_manager.prime_async(
                        device=target_device,
                        open_device=open_device,
                        backend=backend,
                    )
                    opened = True

            if not opened:
                devices = app._device_registry.list_devices()
                fallback = devices[0] if devices else None
                if fallback is not None:
                    open_device, backend = resolve_device_open_target(fallback)
                    app._capture_manager.prime_async(
                        device=fallback["index"],
                        open_device=open_device,
                        backend=int(backend or cv2.CAP_MSMF),
                    )
                    opened = True

            return jsonify({"status": "reset", "persistent_opening": opened})

    @app.route("/api/receive/preview")
    def api_receive_preview():
        return create_preview_response(app)

    @app.route("/api/receive/preview/settings", methods=["POST"])
    def api_preview_settings():
        worker = app._receiver_worker
        if worker is None:
            return jsonify({"error": "No active worker"}), 409

        data = request.get_json(force=True)
        if "quality" in data:
            worker._preview_quality = max(10, min(100, int(data["quality"])))
        if "scale" in data:
            worker._preview_scale = max(0.25, min(1.0, float(data["scale"])))
        if "fps" in data:
            worker._preview_target_fps = max(1.0, min(120.0, float(data["fps"])))
        return jsonify({
            "quality": worker._preview_quality,
            "scale": worker._preview_scale,
            "fps": worker._preview_target_fps,
        })

    @app.route("/api/receive/events")
    def api_receive_events():
        def generate():
            worker = app._receiver_worker
            if worker is None:
                yield _sse("error", {"message": "No active session"})
                return

            event_queue = worker.subscribe()
            try:
                while True:
                    try:
                        event = event_queue.get(timeout=1.0)
                        yield _sse(event["type"], event["data"])
                        if event["type"] in ("complete", "error", "stopped"):
                            break
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        if worker is None or not worker.is_alive():
                            yield _sse("stopped", {"message": "Worker ended"})
                            break
            finally:
                worker.unsubscribe(event_queue)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
