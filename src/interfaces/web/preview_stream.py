"""Preview stream helpers for the web receiver."""

from __future__ import annotations

import time

from flask import Flask, Response, request


def _clamp_int(value: str | None, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except Exception:
        return default


def _clamp_float(value: str | None, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return default


def create_preview_response(app: Flask) -> Response:
    import cv2

    idle_quality = _clamp_int(request.args.get("quality"), 10, 100, 75)
    idle_scale = _clamp_float(request.args.get("scale"), 0.25, 1.0, 1.0)
    idle_fps = _clamp_float(request.args.get("idle_fps"), 1.0, 60.0, 20.0)

    def generate():
        last_worker = None
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
                ret, frame = app._capture_manager.read()
                if not ret or frame is None:
                    time.sleep(0.05)
                    continue

                if idle_scale < 1.0:
                    height, width = frame.shape[:2]
                    scaled_width = max(1, int(width * idle_scale))
                    scaled_height = max(1, int(height * idle_scale))
                    frame = cv2.resize(
                        frame,
                        (scaled_width, scaled_height),
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

    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )
