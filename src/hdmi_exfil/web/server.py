"""Flask web server for HDMI Exfil -- sender & receiver in the browser."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from hdmi_exfil.core.config import PROFILES
from hdmi_exfil.receiver.capture.source import _try_open
from hdmi_exfil.web.receiver_worker import ReceiverWorker

log = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).resolve().parent / ".device_cache.json"


def _load_disk_cache() -> list[dict] | None:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            if isinstance(data, list) and data:
                return data
    except Exception:
        pass
    return None


def _save_disk_cache(devices: list[dict]) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(devices))
    except Exception:
        pass


def _find_sender_html() -> Path:
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidate = root / "sender.html"
    if candidate.is_file():
        return candidate
    env_root = os.environ.get("HDMI_EXFIL_ROOT")
    if env_root:
        candidate = Path(env_root) / "sender.html"
        if candidate.is_file():
            return candidate
    return candidate


def create_app(output_dir: str = "received_files") -> Flask:
    static_dir = Path(__file__).resolve().parent / "static"
    sender_html = _find_sender_html()

    app = Flask(__name__, static_folder=str(static_dir))
    app.config["OUTPUT_DIR"] = output_dir
    app.config["SENDER_HTML"] = str(sender_html)
    app._receiver_worker: ReceiverWorker | None = None

    # Device cache: memory + disk
    app._devices: list[dict] = _load_disk_cache() or []
    app._devices_lock = threading.Lock()

    # Pre-warmed capture
    app._warm_cap: cv2.VideoCapture | None = None
    app._warm_device_idx: int | None = None
    app._warm_lock = threading.Lock()
    app._warming = False  # prevents duplicate warm threads

    def _warm_device(device_idx: int, backend: int) -> None:
        """Open a capture device in background so Start is instant."""
        try:
            cap = _try_open(device_idx, backend, 1920, 1080, 60)
            if cap is not None:
                with app._warm_lock:
                    if app._warm_cap is not None:
                        app._warm_cap.release()
                    app._warm_cap = cap
                    app._warm_device_idx = device_idx
                    log.info("Pre-warmed device %d", device_idx)
        except Exception:
            log.exception("Failed to pre-warm device %d", device_idx)
        finally:
            app._warming = False

    def _start_warm(device_idx: int) -> None:
        """Start warming a device if not already warming."""
        if app._warming:
            return
        backend = None
        with app._devices_lock:
            for d in app._devices:
                if d["index"] == device_idx:
                    backend = d.get("backend")
                    break
        if backend is None:
            return
        app._warming = True
        threading.Thread(target=_warm_device, args=(device_idx, backend), daemon=True).start()

    def _take_warm(device_idx: int) -> cv2.VideoCapture | None:
        with app._warm_lock:
            if app._warm_device_idx == device_idx and app._warm_cap is not None:
                cap = app._warm_cap
                app._warm_cap = None
                app._warm_device_idx = None
                if cap.isOpened():
                    return cap
                cap.release()
        return None

    # On startup, if we have a disk cache, pre-warm the first device
    if app._devices:
        _start_warm(app._devices[0]["index"])

    # ── Page routes ──────────────────────────────────────────────

    @app.route("/")
    def index():
        return send_from_directory(str(static_dir), "receiver.html")

    @app.route("/history")
    def history_page():
        return send_from_directory(str(static_dir), "history.html")

    @app.route("/settings")
    def settings_page():
        return send_from_directory(str(static_dir), "settings.html")

    @app.route("/sender")
    def sender_page():
        return send_from_directory(str(static_dir), "sender-page.html")

    @app.route("/sender/app")
    def sender_app():
        path = app.config["SENDER_HTML"]
        if not os.path.isfile(path):
            return "sender.html not found", 404
        return send_file(path)

    # ── API routes ───────────────────────────────────────────────

    @app.route("/api/devices")
    def api_devices():
        force = request.args.get("force", "0") == "1"
        with app._devices_lock:
            if not force and app._devices:
                return jsonify(app._devices)
        from hdmi_exfil.receiver.cli.console import _detect_devices
        devices = _detect_devices()
        with app._devices_lock:
            app._devices = devices
        _save_disk_cache(devices)
        # Pre-warm first device
        if devices:
            _start_warm(devices[0]["index"])
        return jsonify(devices)

    @app.route("/api/devices/warm", methods=["POST"])
    def api_warm_device():
        """Pre-warm a specific device so Start is instant."""
        data = request.get_json(force=True)
        device_idx = int(data.get("device", 0))
        with app._warm_lock:
            if app._warm_device_idx == device_idx:
                return jsonify({"status": "already_warm"})
        _start_warm(device_idx)
        return jsonify({"status": "warming"})

    @app.route("/api/profiles")
    def api_profiles():
        out = {}
        for name, p in PROFILES.items():
            out[name] = {
                "name": p.name, "width": p.width, "height": p.height,
                "block_size": p.block_size, "target_fps": p.target_fps,
                "fount_bytes_per_frame": p.fount_bytes_per_frame,
            }
        return jsonify(out)

    @app.route("/api/receive/start", methods=["POST"])
    def api_receive_start():
        if app._receiver_worker is not None and app._receiver_worker.is_alive():
            return jsonify({"error": "Already receiving"}), 409

        data = request.get_json(force=True)
        device = int(data.get("device", 0))
        profile_name = data.get("profile", "speed")
        mode = data.get("mode", "auto")
        output = data.get("output", app.config["OUTPUT_DIR"])

        profile = PROFILES.get(profile_name)
        if profile is None:
            return jsonify({"error": f"Unknown profile: {profile_name}"}), 400

        backend = None
        with app._devices_lock:
            for d in app._devices:
                if d["index"] == device:
                    backend = d.get("backend")
                    break

        # If device list is empty, detect now (race condition fix)
        if backend is None:
            from hdmi_exfil.receiver.cli.console import _detect_devices
            devices = _detect_devices()
            with app._devices_lock:
                app._devices = devices
            _save_disk_cache(devices)
            for d in devices:
                if d["index"] == device:
                    backend = d.get("backend")
                    break

        precap = _take_warm(device)

        worker = ReceiverWorker(
            device=device, profile=profile,
            mode=mode, output_dir=output,
            backend=backend, precap=precap,
        )
        app._receiver_worker = worker
        worker.start()
        return jsonify({"status": "started"})

    @app.route("/api/receive/stop", methods=["POST"])
    def api_receive_stop():
        worker = app._receiver_worker
        if worker is None or not worker.is_alive():
            return jsonify({"error": "Not receiving"}), 409
        worker.stop()
        # Re-warm the same device for next Start
        _start_warm(worker._device)
        return jsonify({"status": "stopped"})

    @app.route("/api/receive/events")
    def api_receive_events():
        def generate():
            worker = app._receiver_worker
            if worker is None:
                yield _sse("error", {"message": "No active session"})
                return
            eq = worker.subscribe()
            try:
                while True:
                    try:
                        event = eq.get(timeout=1.0)
                        yield _sse(event["type"], event["data"])
                        if event["type"] in ("complete", "error", "stopped"):
                            break
                    except queue.Empty:
                        yield ": keepalive\n\n"
                        if worker is None or not worker.is_alive():
                            yield _sse("stopped", {"message": "Worker ended"})
                            break
            finally:
                worker.unsubscribe(eq)
        return Response(generate(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    @app.route("/api/receive/download/<path:filename>")
    def api_download(filename):
        output = app.config["OUTPUT_DIR"]
        safe = os.path.basename(filename)
        path = os.path.join(output, safe)
        if not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404
        return send_file(path, as_attachment=True)

    return app


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
