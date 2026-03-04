"""Flask web server for HDMI Exfil -- sender & receiver in the browser.

Serves the existing ``sender.html`` (from project root) and a new
``receiver.html`` (self-contained) from a single Flask app.  The receiver
backend runs in a background thread (``ReceiverWorker``) and publishes
events via Server-Sent Events to the browser for real-time progress.

Usage::

    from hdmi_exfil.web.server import create_app
    app = create_app()
    app.run()
"""

from __future__ import annotations

import json
import os
import queue
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from hdmi_exfil.core.config import PROFILES
from hdmi_exfil.web.receiver_worker import ReceiverWorker


def _find_sender_html() -> Path:
    """Locate sender.html at the project root."""
    # Walk up: web/ -> hdmi_exfil/ -> src/ -> project root
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidate = root / "sender.html"
    if candidate.is_file():
        return candidate
    # Fallback: env var
    env_root = os.environ.get("HDMI_EXFIL_ROOT")
    if env_root:
        candidate = Path(env_root) / "sender.html"
        if candidate.is_file():
            return candidate
    return candidate  # may not exist; route returns 404


def create_app(output_dir: str = "received_files") -> Flask:
    """Application factory for the HDMI Exfil web server."""
    static_dir = Path(__file__).resolve().parent / "static"
    sender_html = _find_sender_html()

    app = Flask(__name__, static_folder=str(static_dir))
    app.config["OUTPUT_DIR"] = output_dir
    app.config["SENDER_HTML"] = str(sender_html)
    app._receiver_worker: ReceiverWorker | None = None

    # ----------------------------------------------------------------
    # Page routes
    # ----------------------------------------------------------------

    @app.route("/")
    def index():
        return send_from_directory(str(static_dir), "receiver.html")

    @app.route("/history")
    def history_page():
        return send_from_directory(str(static_dir), "history.html")

    @app.route("/sender")
    def sender_page():
        return send_from_directory(str(static_dir), "sender-page.html")

    @app.route("/sender/app")
    def sender_app():
        path = app.config["SENDER_HTML"]
        if not os.path.isfile(path):
            return "sender.html not found", 404
        return send_file(path)

    # ----------------------------------------------------------------
    # API routes
    # ----------------------------------------------------------------

    @app.route("/api/devices")
    def api_devices():
        from hdmi_exfil.receiver.cli.console import _detect_devices
        devices = _detect_devices()
        return jsonify(devices)

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

        worker = ReceiverWorker(
            device=device, profile=profile,
            mode=mode, output_dir=output,
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
