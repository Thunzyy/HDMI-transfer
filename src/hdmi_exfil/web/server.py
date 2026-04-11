"""Flask web server for HDMI Exfil -- sender & receiver in the browser."""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from hdmi_exfil.adapters.capture.capture_manager import CaptureManager
from hdmi_exfil.adapters.capture.device_registry import DeviceRegistry
from hdmi_exfil.core.config import PROFILES
from hdmi_exfil.receiver.capture.source import open_capture
from hdmi_exfil.web.receiver_worker import ReceiverWorker

log = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).resolve().parent / ".device_cache.json"


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


def _save_disk_cache(devices: list[dict]) -> None:
    """Compatibility helper kept for tests and legacy callers."""
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


def _reveal_in_file_manager(path: str) -> tuple[str, str]:
    target = Path(path).resolve()
    parent = target.parent

    if target.exists():
        if sys.platform == "win32":
            subprocess.Popen([
                "explorer.exe",
                "/select,",
                os.path.normpath(str(target)),
            ])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(parent)])
        return "file", str(target)

    if not parent.exists():
        raise FileNotFoundError(f"Directory not found: {parent}")

    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", os.path.normpath(str(parent))])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(parent)])
    else:
        subprocess.Popen(["xdg-open", str(parent)])
    return "directory", str(parent)


def create_app(output_dir: str = "received_files") -> Flask:
    static_dir = Path(__file__).resolve().parent / "static"
    sender_html = _find_sender_html()

    app = Flask(__name__, static_folder=str(static_dir))
    app.config["OUTPUT_DIR"] = output_dir
    app.config["SENDER_HTML"] = str(sender_html)
    app._receiver_worker: ReceiverWorker | None = None
    app._receiver_control_lock = threading.Lock()
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

    def _detect_and_cache() -> list[dict]:
        """Run device detection under the registry lock and cache results."""
        from hdmi_exfil.receiver.cli.console import _detect_devices
        return app._device_registry.detect(_detect_devices)

    def _resolve_output_file(filename: str) -> tuple[str, str]:
        safe = os.path.basename(filename)
        path = os.path.abspath(os.path.join(app.config["OUTPUT_DIR"], safe))
        return safe, path

    # On startup, if we have a disk cache, open persistent cap for first device
    cached_devices = app._device_registry.list_devices()
    if cached_devices:
        d0 = cached_devices[0]
        app._capture_manager.prime_async(
            device=d0["index"],
            backend=d0.get("backend", cv2.CAP_MSMF),
        )

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

        # Release persistent cap before detection (avoids camera contention)
        log.info("[pcap] /api/devices: releasing persistent for detection")
        app._capture_manager.release()
        devices = _detect_and_cache()

        # Open persistent cap for the first device
        if devices:
            d0 = devices[0]
            app._capture_manager.prime(
                device=d0["index"],
                backend=d0.get("backend", cv2.CAP_MSMF),
            )
        return jsonify(devices)

    @app.route("/api/devices/warm", methods=["POST"])
    def api_warm_device():
        """Switch persistent cap to a specific device."""
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
            out = {"active": True}
            try:
                out.update(worker.get_preview_health())
            except Exception:
                pass
            return jsonify(out)
        return jsonify({"active": False})

    @app.route("/api/receive/start", methods=["POST"])
    def api_receive_start():
        with app._receiver_control_lock:
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

            backend = app._device_registry.get_backend(device)
            device_info = app._device_registry.get_device(device)

            decode_device = device
            decode_backend = backend
            prefer_dshow = bool(
                sys.platform == "win32"
                and device_info is not None
                and device_info.get("prefer_dshow")
                and device_info.get("dshow_index") is not None
            )
            if prefer_dshow:
                decode_device = int(device_info["dshow_index"])
                decode_backend = int(cv2.CAP_DSHOW)
                log.info(
                    "[pcap] START: using DSHOW path for capture card "
                    "(logical_index=%d -> dshow_index=%d)",
                    device, decode_device,
                )
                # Persistent cap currently tracks MSMF devices; release it before
                # opening DSHOW to avoid backend contention on the same hardware.
                app._capture_manager.release()

            # If backend unknown, detect devices now (race-condition fallback)
            if decode_backend is None:
                app._capture_manager.release()
                devices = _detect_and_cache()
                for d in devices:
                    if d["index"] == device:
                        decode_backend = d.get("backend")
                        device_info = d
                        break
                if (
                    sys.platform == "win32"
                    and device_info is not None
                    and device_info.get("prefer_dshow")
                    and device_info.get("dshow_index") is not None
                ):
                    decode_device = int(device_info["dshow_index"])
                    decode_backend = int(cv2.CAP_DSHOW)
                    app._capture_manager.release()

            precap = None
            on_cap_return = None
            if decode_backend == cv2.CAP_DSHOW:
                # Do not reuse MSMF persistent capture path with DSHOW workers.
                on_cap_return = None
            else:
                # Wait for persistent cap if it's still opening (startup race)
                log.info("[pcap] START: waiting for persistent_ready (device=%d)...", device)
                ready = app._capture_manager.wait_until_ready(timeout=10.0)
                log.info("[pcap] START: persistent_ready=%s", ready)
                precap, _ = app._capture_manager.take(device=device)
                log.info("[pcap] START: precap=%s", "YES" if precap else "NO")
                on_cap_return = (
                    lambda raw_cap, decode_device=decode_device, decode_backend=decode_backend:
                    app._capture_manager.return_capture(
                        capture=raw_cap,
                        device=decode_device,
                        backend=decode_backend,
                    )
                )

            worker = ReceiverWorker(
                device=decode_device, profile=profile,
                mode=mode, output_dir=output,
                backend=decode_backend, precap=precap,
                on_cap_return=on_cap_return,
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
            # Capture is returned via the manager callback automatically.
            return jsonify({"status": "stopped"})

    @app.route("/api/receive/reset", methods=["POST"])
    def api_receive_reset():
        """Force-close stale receive session and reopen persistent capture."""
        with app._receiver_control_lock:
            worker = app._receiver_worker
            if worker is not None and worker.is_alive():
                worker.stop()
            app._receiver_worker = None

            # Tear down any stale persistent handle first.
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
                backend = app._device_registry.get_backend(target_device)
                if backend is None:
                    devices = _detect_and_cache()
                    for d in devices:
                        if d["index"] == target_device:
                            backend = d.get("backend")
                            break
                if backend is not None:
                    app._capture_manager.prime_async(
                        device=target_device,
                        backend=backend,
                    )
                    opened = True

            if not opened:
                devices = app._device_registry.list_devices()
                fallback = devices[0] if devices else None
                if fallback is not None:
                    app._capture_manager.prime_async(
                        device=fallback["index"],
                        backend=fallback.get("backend", cv2.CAP_MSMF),
                    )
                    opened = True

            return jsonify({"status": "reset", "persistent_opening": opened})

    @app.route("/api/receive/preview")
    def api_receive_preview():
        """Low-latency MJPEG preview stream (active worker or idle device)."""
        def clamp_int(value: str | None, lo: int, hi: int, default: int) -> int:
            try:
                return max(lo, min(hi, int(value)))
            except Exception:
                return default

        def clamp_float(value: str | None, lo: float, hi: float, default: float) -> float:
            try:
                return max(lo, min(hi, float(value)))
            except Exception:
                return default

        idle_quality = clamp_int(request.args.get("quality"), 10, 100, 75)
        idle_scale = clamp_float(request.args.get("scale"), 0.25, 1.0, 1.0)
        idle_fps = clamp_float(request.args.get("idle_fps"), 1.0, 60.0, 20.0)

        def generate():
            last_worker: ReceiverWorker | None = None
            last_seq = 0
            while True:
                worker = app._receiver_worker
                if worker is not None and worker.is_alive():
                    if worker is not last_worker:
                        last_worker = worker
                        last_seq = 0

                    jpeg, seq = worker.wait_for_preview(last_seq, timeout_s=1.0)
                    if jpeg is None or seq <= last_seq:
                        continue
                    last_seq = seq
                else:
                    # Idle preview: read directly from the persistent capture.
                    ret, frame = app._capture_manager.read()
                    if not ret or frame is None:
                        time.sleep(0.05)
                        continue

                    if idle_scale < 1.0:
                        h, w = frame.shape[:2]
                        nw = max(1, int(w * idle_scale))
                        nh = max(1, int(h * idle_scale))
                        frame = cv2.resize(
                            frame,
                            (nw, nh),
                            interpolation=cv2.INTER_AREA,
                        )

                    ok, encoded = cv2.imencode(
                        ".jpg",
                        frame,
                        [cv2.IMWRITE_JPEG_QUALITY, idle_quality],
                    )
                    if not ok:
                        time.sleep(0.01)
                        continue
                    jpeg = encoded.tobytes()
                    time.sleep(1.0 / idle_fps)

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
        return Response(generate(),
                        mimetype="multipart/x-mixed-replace; boundary=frame",
                        headers={
                            "Cache-Control": "no-cache, no-store, must-revalidate",
                            "Pragma": "no-cache",
                            "Expires": "0",
                            "X-Accel-Buffering": "no",
                        })

    @app.route("/api/receive/preview/settings", methods=["POST"])
    def api_preview_settings():
        """Update preview quality/scale on the fly."""
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
        _, path = _resolve_output_file(filename)
        if not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404
        return send_file(path, as_attachment=True)

    @app.route("/api/receive/files")
    def api_receive_files():
        root = Path(app.config["OUTPUT_DIR"]).resolve()
        if not root.exists():
            return jsonify([])

        files: list[dict] = []
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_file():
                continue
            stat = child.stat()
            files.append({
                "filename": child.name,
                "system_path": str(child.resolve()),
                "size": stat.st_size,
                "modified_ms": int(stat.st_mtime * 1000),
            })
        return jsonify(files)

    @app.route("/api/receive/file/<path:filename>", methods=["GET", "DELETE"])
    def api_receive_file(filename):
        safe, path = _resolve_output_file(filename)
        exists = os.path.isfile(path)

        if request.method == "GET":
            payload = {
                "filename": safe,
                "system_path": path,
                "exists": exists,
            }
            if exists:
                payload["size"] = os.path.getsize(path)
            return jsonify(payload)

        if not exists:
            return jsonify({
                "error": "File not found",
                "filename": safe,
                "system_path": path,
                "exists": False,
            }), 404

        try:
            os.remove(path)
        except OSError as exc:
            return jsonify({
                "error": str(exc),
                "filename": safe,
                "system_path": path,
                "exists": True,
            }), 409
        return jsonify({
            "status": "deleted",
            "filename": safe,
            "system_path": path,
            "exists": False,
        })

    @app.route("/api/receive/file/<path:filename>/reveal", methods=["POST"])
    def api_receive_file_reveal(filename):
        safe, path = _resolve_output_file(filename)
        try:
            opened_kind, opened_path = _reveal_in_file_manager(path)
        except FileNotFoundError:
            return jsonify({
                "error": "File location not found",
                "filename": safe,
                "system_path": path,
                "exists": False,
            }), 404
        except OSError as exc:
            return jsonify({
                "error": str(exc),
                "filename": safe,
                "system_path": path,
                "exists": os.path.isfile(path),
            }), 409

        return jsonify({
            "status": "revealed",
            "opened": opened_kind,
            "opened_path": opened_path,
            "filename": safe,
            "system_path": path,
            "exists": os.path.isfile(path),
        })

    return app


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
