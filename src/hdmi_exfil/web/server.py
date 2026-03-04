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

    # Global device-open lock: prevents _detect_devices and persistent cap
    # open from fighting over the same MSMF device simultaneously.
    app._device_open_lock = threading.Lock()

    # Persistent capture — stays open while the web app runs.
    # Handed to the worker on START, returned on STOP. Zero open delay.
    app._persistent_cap: cv2.VideoCapture | None = None
    app._persistent_device_idx: int | None = None
    app._persistent_backend: int | None = None
    app._persistent_lock = threading.Lock()
    app._persistent_ready = threading.Event()

    def _open_persistent(device_idx: int, backend: int) -> None:
        """Open a device and keep it as the persistent capture."""
        log.info("[pcap] Opening persistent cap: device=%d backend=%d", device_idx, backend)
        app._persistent_ready.clear()
        with app._persistent_lock:
            old = app._persistent_cap
            app._persistent_cap = None
            app._persistent_device_idx = None
            app._persistent_backend = None
        if old is not None:
            log.info("[pcap] Releasing old persistent cap")
            old.release()

        try:
            t0 = time.time()
            with app._device_open_lock:
                cap = _try_open(device_idx, backend, 1920, 1080, 60)
            dt = time.time() - t0
            if cap is not None:
                with app._persistent_lock:
                    app._persistent_cap = cap
                    app._persistent_device_idx = device_idx
                    app._persistent_backend = backend
                log.info("[pcap] Persistent cap READY: device=%d (%.1fs)", device_idx, dt)
            else:
                log.warning("[pcap] FAILED to open persistent cap: device=%d (%.1fs)", device_idx, dt)
        finally:
            app._persistent_ready.set()

    def _open_persistent_bg(device_idx: int, backend: int) -> None:
        """Open the persistent cap in a background thread."""
        log.info("[pcap] Starting background open: device=%d", device_idx)
        threading.Thread(
            target=_open_persistent,
            args=(device_idx, backend),
            daemon=True,
        ).start()

    def _release_persistent() -> None:
        """Release the persistent capture."""
        with app._persistent_lock:
            cap = app._persistent_cap
            app._persistent_cap = None
            app._persistent_device_idx = None
            app._persistent_backend = None
        if cap is not None:
            log.info("[pcap] Releasing persistent cap")
            cap.release()

    def _take_persistent(device_idx: int) -> tuple[cv2.VideoCapture | None, int | None]:
        """Take the persistent cap if it matches the requested device.

        Returns (cap, backend) or (None, None).
        """
        with app._persistent_lock:
            log.info("[pcap] _take_persistent: requested=%d, have=%s (cap=%s)",
                     device_idx, app._persistent_device_idx,
                     "open" if app._persistent_cap and app._persistent_cap.isOpened() else "none")
            if app._persistent_device_idx == device_idx and app._persistent_cap is not None:
                cap = app._persistent_cap
                backend = app._persistent_backend
                app._persistent_cap = None
                app._persistent_device_idx = None
                app._persistent_backend = None
                if cap.isOpened():
                    log.info("[pcap] TAKEN persistent cap for device %d", device_idx)
                    return cap, backend
                log.warning("[pcap] Persistent cap was closed, releasing")
                cap.release()
        return None, None

    def _return_cap(raw_cap: cv2.VideoCapture) -> None:
        """Callback: worker returns its cap for reuse."""
        with app._persistent_lock:
            old = app._persistent_cap
            app._persistent_cap = raw_cap
            # Restore index/backend from what worker used
            worker = app._receiver_worker
            if worker is not None:
                app._persistent_device_idx = worker._device
                app._persistent_backend = worker._backend
        if old is not None:
            old.release()
        app._persistent_ready.set()
        log.info("Cap returned from worker — persistent again")

    def _get_backend_for(device_idx: int) -> int | None:
        """Look up the backend for a device index from the cache."""
        with app._devices_lock:
            for d in app._devices:
                if d["index"] == device_idx:
                    return d.get("backend")
        return None

    def _detect_and_cache() -> list[dict]:
        """Run device detection under the device-open lock and cache results."""
        from hdmi_exfil.receiver.cli.console import _detect_devices
        with app._device_open_lock:
            devices = _detect_devices()
        with app._devices_lock:
            app._devices = devices
        _save_disk_cache(devices)
        return devices

    # On startup, if we have a disk cache, open persistent cap for first device
    if app._devices:
        d0 = app._devices[0]
        _open_persistent_bg(d0["index"], d0.get("backend", cv2.CAP_MSMF))

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
        log.info("[pcap] /api/devices called (force=%s)", force)
        with app._devices_lock:
            if not force and app._devices:
                log.info("[pcap] /api/devices returning %d cached devices", len(app._devices))
                return jsonify(app._devices)

        # Release persistent cap before detection (avoids camera contention)
        log.info("[pcap] /api/devices: releasing persistent for detection")
        _release_persistent()
        devices = _detect_and_cache()

        # Open persistent cap for the first device
        if devices:
            d0 = devices[0]
            _open_persistent(d0["index"], d0.get("backend", cv2.CAP_MSMF))
        return jsonify(devices)

    @app.route("/api/devices/warm", methods=["POST"])
    def api_warm_device():
        """Switch persistent cap to a specific device."""
        data = request.get_json(force=True)
        device_idx = int(data.get("device", 0))
        log.info("[pcap] /api/devices/warm called: device=%d", device_idx)
        with app._persistent_lock:
            if app._persistent_device_idx == device_idx and app._persistent_cap is not None:
                log.info("[pcap] /api/devices/warm: already open for device %d", device_idx)
                return jsonify({"status": "already_open"})
        backend = _get_backend_for(device_idx)
        if backend is None:
            return jsonify({"status": "unknown_device"}), 400
        _open_persistent_bg(device_idx, backend)
        return jsonify({"status": "opening"})

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

    @app.route("/api/receive/status")
    def api_receive_status():
        """Return current receiver state so the UI can recover after refresh."""
        worker = app._receiver_worker
        if worker is not None and worker.is_alive():
            return jsonify({"active": True})
        return jsonify({"active": False})

    @app.route("/api/receive/start", methods=["POST"])
    def api_receive_start():
        # Auto-stop previous worker if still alive (e.g. page refresh)
        old = app._receiver_worker
        if old is not None and old.is_alive():
            log.info("Auto-stopping previous worker before new START")
            old.stop()
            app._receiver_worker = None

        data = request.get_json(force=True)
        device = int(data.get("device", 0))
        profile_name = data.get("profile", "speed")
        mode = data.get("mode", "auto")
        output = data.get("output", app.config["OUTPUT_DIR"])

        bpc = int(data.get("bpc", 1))
        if bpc not in (1, 2, 3):
            bpc = 1

        base = PROFILES.get(profile_name)
        if base is None:
            return jsonify({"error": f"Unknown profile: {profile_name}"}), 400

        from dataclasses import replace
        profile = replace(base, bits_per_channel=bpc)

        backend = _get_backend_for(device)

        # If backend unknown, detect devices now (race-condition fallback)
        if backend is None:
            _release_persistent()
            devices = _detect_and_cache()
            for d in devices:
                if d["index"] == device:
                    backend = d.get("backend")
                    break

        # Wait for persistent cap if it's still opening (startup race)
        log.info("[pcap] START: waiting for persistent_ready (device=%d)...", device)
        ready = app._persistent_ready.wait(timeout=10.0)
        log.info("[pcap] START: persistent_ready=%s", ready)
        precap, _ = _take_persistent(device)
        log.info("[pcap] START: precap=%s", "YES" if precap else "NO")

        worker = ReceiverWorker(
            device=device, profile=profile,
            mode=mode, output_dir=output,
            backend=backend, precap=precap,
            on_cap_return=_return_cap,
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
        # Cap is returned via _return_cap callback automatically
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
