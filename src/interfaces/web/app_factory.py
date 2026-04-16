"""Flask app factory for HDMI Transfer web interfaces."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from flask import Flask, send_file, send_from_directory

_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = _SOURCE_ROOT / "web" / "static"
CACHE_FILE = _SOURCE_ROOT / "web" / ".device_cache.json"


def _load_disk_cache() -> list[dict] | None:
    """Compatibility helper kept for tests and legacy callers."""
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            if isinstance(data, list) and data:
                return data
    except Exception:
        pass
    return None


def _find_sender_html() -> Path:
    candidate = _REPO_ROOT / "sender.html"
    if candidate.is_file():
        return candidate
    env_root = os.environ.get("HDMI_EXFIL_ROOT")
    if env_root:
        candidate = Path(env_root) / "sender.html"
        if candidate.is_file():
            return candidate
    return candidate


def _should_prime_persistent_capture(open_device: int | str, backend: int | None) -> bool:
    return not isinstance(open_device, str)


def shutdown_runtime(app: Flask) -> None:
    """Stop background worker and release persistent capture resources."""
    lock = getattr(app, "_receiver_control_lock", None)
    worker = getattr(app, "_receiver_worker", None)
    capture_manager = getattr(app, "_capture_manager", None)

    if lock is not None:
        lock.acquire()
    try:
        if worker is not None:
            try:
                if worker.is_alive():
                    worker.stop()
            finally:
                app._receiver_worker = None
        if capture_manager is not None:
            capture_manager.release()
    finally:
        if lock is not None:
            lock.release()


def _register_page_routes(app: Flask, static_dir: Path) -> None:
    def _send_sender_html():
        path = app.config["SENDER_HTML"]
        if not os.path.isfile(path):
            return "sender.html not found", 404
        return send_file(path)

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

    @app.route("/sender/page")
    def sender_page_wrapper():
        return send_from_directory(str(static_dir), "sender-page.html")

    @app.route("/sender/test")
    def sender_test_page():
        return send_from_directory(str(static_dir), "sender-test-page.html")

    @app.route("/sender/app")
    def sender_app():
        return _send_sender_html()

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            str(static_dir), "logo_hdmi_static.svg", mimetype="image/svg+xml"
        )


def create_app(
    output_dir: str = "received_files",
    *,
    runtime: bool = True,
) -> Flask:
    from .routes_devices import register_device_routes
    from .routes_files import register_file_routes
    from .routes_receive import register_receive_routes

    sender_html = _find_sender_html()

    app = Flask(__name__, static_folder=str(STATIC_DIR))
    app.config["OUTPUT_DIR"] = output_dir
    app.config["SENDER_HTML"] = str(sender_html)
    app._receiver_worker = None
    app._receiver_control_lock = threading.Lock()
    app.shutdown_runtime = lambda: shutdown_runtime(app)

    if runtime:
        import cv2

        from hdmi_transfer.adapters.capture.capture_manager import CaptureManager
        from hdmi_transfer.adapters.capture.device_registry import (
            DeviceRegistry,
            resolve_device_open_target,
        )
        from hdmi_transfer.receiver.capture.source import open_capture

        app._device_registry = DeviceRegistry(CACHE_FILE)

        preloaded_devices = _load_disk_cache()
        if preloaded_devices is not None:
            app._device_registry.replace(preloaded_devices)

        app._capture_manager = CaptureManager(
            opener=open_capture,
            width=1920,
            height=1080,
            fps=60,
            open_lock=app._device_registry.open_lock,
        )

        def detect_and_cache() -> list[dict]:
            from hdmi_transfer.receiver.cli.console import _detect_devices

            return app._device_registry.detect(_detect_devices)

        app._detect_and_cache = detect_and_cache

        cached_devices = app._device_registry.list_devices()
        if cached_devices:
            device = cached_devices[0]
            open_device, backend = resolve_device_open_target(device)
            if _should_prime_persistent_capture(open_device, backend):
                app._capture_manager.prime_async(
                    device=device["index"],
                    open_device=open_device,
                    backend=int(backend or cv2.CAP_MSMF),
                )
    else:
        app._device_registry = None
        app._capture_manager = None
        app._detect_and_cache = lambda: []

    _register_page_routes(app, STATIC_DIR)
    register_device_routes(app)
    register_receive_routes(app)
    register_file_routes(app)
    return app
