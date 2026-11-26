"""Receiver HTTP routes."""

from __future__ import annotations

import json
import logging
import queue
from dataclasses import replace

from flask import Flask, Response, jsonify, request

from hdmi_transfer.adapters.capture.device_registry import (
    list_device_open_targets,
    resolve_device_open_target,
)
from hdmi_transfer.core.config import PROFILES
from hdmi_transfer.domain.transfer_defaults import (
    DEFAULT_PROFILE_NAME, DEFAULT_MODE, DEFAULT_BITS_PER_CHANNEL,
)

from .preview_stream import create_preview_response

log = logging.getLogger(__name__)


def _should_prime_persistent_capture(open_device: int | str, backend: int | None) -> bool:
    return not isinstance(open_device, str)


def resolve_profile_device(devices: list[dict], profile: dict) -> int | None:
    """Find a sender profile's capture card.

    The saved index wins while it still points to a card with the saved name (one
    card can be listed several times, once per mode). Otherwise the first card
    with that name, and the saved index as a last resort.
    """
    name = profile.get("device_name")
    index = profile.get("device_index")
    if name:
        named = [device for device in devices if device.get("name") == name]
        for device in named:
            if index is not None and int(device["index"]) == int(index):
                return int(index)
        if named:
            return int(named[0]["index"])
    return int(index) if index is not None else None


def start_receiver_worker(
    app: Flask,
    settings: dict,
    *,
    force_recalibration: bool = False,
    profile_id: int | None = None,
    skip_identity: tuple[str, int, str] | None = None,
    calibrate_only: bool = False,
):
    """Start one receiver worker. Used by ``/api/receive/start`` and auto receive.

    Caller holds ``app._receiver_control_lock``. Raises ``ValueError`` for an
    unknown transfer profile.
    """
    import cv2

    from hdmi_transfer.adapters.receive_worker import ReceiverWorker

    old_worker = app._receiver_worker
    if old_worker is not None and old_worker.is_alive():
        log.info("Auto-stopping previous worker before new START")
        old_worker.stop(reason="replaced")
        app._receiver_worker = None

    device = int(settings.get("device", 0))
    profile_name = settings.get("profile", DEFAULT_PROFILE_NAME)
    mode = settings.get("mode", DEFAULT_MODE)
    output = settings.get("output", app.config["OUTPUT_DIR"])
    require_preflight = bool(settings.get("preflight", True))
    bpc = int(settings.get("bpc", DEFAULT_BITS_PER_CHANNEL))
    if bpc not in (1, 2, 3):
        bpc = DEFAULT_BITS_PER_CHANNEL

    base_profile = PROFILES.get(profile_name)
    if base_profile is None:
        raise ValueError(f"Unknown profile: {profile_name}")

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

    fallback_profile_ids: list[int] = []
    if profile_id is not None:
        fallback_profile_ids = app._profile_store.matching_profile_ids(profile_id)

    def save_calibrated_bpc(calibrated_profile_id: int | None, bpc: int) -> None:
        # The sender's real encoding becomes the sender PC's setting, so the
        # receiver UI and the next Start match the notebook.
        if calibrated_profile_id is not None:
            app._profile_store.update(int(calibrated_profile_id), {"bpc": int(bpc)})

    worker = ReceiverWorker(
        device=decode_device,
        profile=profile,
        mode=mode,
        output_dir=output,
        backend=decode_backend,
        precap=precap,
        on_cap_return=on_cap_return,
        fallback_targets=fallback_targets,
        require_preflight=require_preflight,
        force_recalibration=force_recalibration or calibrate_only,
        calibrate_only=calibrate_only,
        on_calibrated=save_calibrated_bpc if calibrate_only else None,
        device_identity=str((device_info or {}).get("name") or decode_device),
        history_store=app._history_store,
        sender_profile_id=profile_id,
        fallback_profile_ids=fallback_profile_ids,
        skip_identity=skip_identity,
    )
    app._receiver_worker = worker
    worker.start()
    return worker


def start_worker_for_profile(app: Flask, profile: dict):
    """Auto receive entry point: arm a worker with a sender profile's saved settings.

    Returns None without starting when a worker is already running (a manual
    Start or Recalibrate wins) or when auto receive was turned off or paused
    while this call waited for the control lock.
    """
    with app._receiver_control_lock:
        current = app._receiver_worker
        if current is not None and current.is_alive():
            return None
        if not app._profile_store.get_auto_receive() or app._auto_receive.status()["paused"]:
            return None
        if not getattr(app, "_auto_receive_scanned", False):
            # The device cache can be stale after a reboot: scan once before arming unattended.
            app._auto_receive_scanned = True
            devices = app._detect_and_cache()
        else:
            registry = app._device_registry
            devices = registry.list_devices() if registry is not None else []
        device = resolve_profile_device(devices, profile)
        if device is None:
            raise RuntimeError(f"No capture device for {profile.get('name')}")
        return start_receiver_worker(app, {
            "device": device, "profile": profile["profile"], "mode": profile["mode"],
            "bpc": profile["bpc"], "preflight": True,
        }, profile_id=profile["id"], skip_identity=app._auto_receive.last_identity)


def register_receive_routes(app: Flask) -> None:
    def _json_with_sender_cors(payload: dict, status_code: int = 200):
        response = jsonify(payload)
        response.status_code = status_code
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.route("/api/receive/status")
    def api_receive_status():
        worker = app._receiver_worker
        if worker is not None:
            payload = {"active": bool(worker.is_alive())}
            try:
                payload.update(worker.get_preview_health())
            except Exception:
                pass
            try:
                payload.update(worker.get_runtime_state())
                app._auto_receive.adopt_match(worker)
            except Exception:
                pass
        else:
            payload = {
                "active": False,
                "preflight_required": False,
                "preflight_state": "inactive",
            }
        payload["active_profile_id"] = app._profile_store.get_active_id()
        payload["auto_receive"] = app._auto_receive.status()
        return _json_with_sender_cors(payload)

    @app.route("/api/receive/start", methods=["POST"])
    def api_receive_start():
        data = request.get_json(force=True)
        profile_id = data.get("profile_id")
        try:
            profile_id = int(profile_id) if profile_id is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid profile_id"}), 400
        if profile_id is not None and app._profile_store.get(profile_id) is None:
            return jsonify({"error": "Unknown sender PC"}), 404
        with app._receiver_control_lock:
            try:
                start_receiver_worker(
                    app, data,
                    force_recalibration=bool(data.get("force_recalibration", False)),
                    profile_id=profile_id,
                    calibrate_only=bool(data.get("calibrate_only", False)),
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
        app._auto_receive.clear_pause()
        return jsonify({"status": "started"})

    @app.route("/api/receive/stop", methods=["POST"])
    def api_receive_stop():
        # Pause first, outside the control lock: auto receive must not re-arm in between.
        worker = app._receiver_worker
        if worker is not None and worker.is_alive() and app._profile_store.get_auto_receive():
            app._auto_receive.pause("Stopped by user")
        with app._receiver_control_lock:
            worker = app._receiver_worker
            if worker is None or not worker.is_alive():
                return jsonify({"error": "Not receiving"}), 409
            worker.stop(reason="user")
        return jsonify({"status": "stopped"})

    @app.route("/api/receive/reset", methods=["POST"])
    def api_receive_reset():
        import cv2

        if app._profile_store.get_auto_receive():
            app._auto_receive.pause("Paused by reset")
        with app._receiver_control_lock:
            worker = app._receiver_worker
            if worker is not None and worker.is_alive():
                worker.stop(reason="user")
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
                    if _should_prime_persistent_capture(open_device, backend):
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
                    if _should_prime_persistent_capture(open_device, backend):
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
            worker._preview_target_fps = max(0.0, min(120.0, float(data["fps"])))
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
