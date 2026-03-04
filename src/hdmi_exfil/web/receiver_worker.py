"""Background receiver worker for the web application.

Runs the capture-decode loop in a daemon thread, publishing structured
events to subscriber queues.  Reuses all existing core modules:
CaptureSource, sample_frame, FountainProtocol, FountainDecoder, etc.

Events published::

    status   - {state, message}
    progress - {chunks_decoded, total_chunks, percent, ...}
    complete - {filename, size, sha256_ok, download_url, ...}
    error    - {message}
    stopped  - {message, frames_captured}
"""

from __future__ import annotations

import base64
import contextlib
import os
import queue
import threading
import time

import cv2
import numpy as np

from hdmi_exfil.core.capture.sampler import sample_frame
from hdmi_exfil.core.config import (
    FRAME_TYPE_DATA,
    FRAME_TYPE_END,
    FRAME_TYPE_START,
    ResolutionProfile,
)
from hdmi_exfil.core.file_handling.metadata import (
    parse_fountain_metadata,
    parse_start_metadata,
)
from hdmi_exfil.core.file_handling.writer import verify_integrity, write_output
from hdmi_exfil.core.protocols import get_protocol
from hdmi_exfil.core.protocols.fountain import FountainDecoder
from hdmi_exfil.receiver.capture.source import CaptureSource


class ReceiverWorker(threading.Thread):
    """Background thread: capture HDMI frames and decode file data.

    Parameters
    ----------
    device:
        Camera index for CaptureSource.
    profile:
        Resolution profile (speed / balanced / quality).
    mode:
        Protocol mode: ``'auto'``, ``'sequential'``, or ``'fountain'``.
    output_dir:
        Directory to save received files.
    """

    def __init__(
        self,
        device: int,
        profile: ResolutionProfile,
        mode: str = "auto",
        output_dir: str = "received_files",
        backend: int | None = None,
        precap: "cv2.VideoCapture | None" = None,
        on_cap_return: "callable | None" = None,
    ) -> None:
        super().__init__(daemon=True)
        self._device = device
        self._profile = profile
        self._mode = mode
        self._output_dir = output_dir
        self._backend = backend
        self._precap = precap
        self._on_cap_return = on_cap_return
        self._stop_event = threading.Event()
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    # -- subscriber management -------------------------------------------

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            with contextlib.suppress(ValueError):
                self._subscribers.remove(q)

    def _publish(self, event_type: str, data: dict) -> None:
        event = {"type": event_type, "data": data}
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5.0)

    # -- preview ---------------------------------------------------------

    def _publish_preview(self, frame) -> None:
        """Encode a frame as a small JPEG thumbnail and publish."""
        try:
            h, w = frame.shape[:2]
            scale = min(320 / w, 180 / h)
            new_w, new_h = int(w * scale), int(h * scale)
            thumb = cv2.resize(frame, (new_w, new_h))
            _, jpeg = cv2.imencode(
                ".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 50],
            )
            b64 = base64.b64encode(jpeg.tobytes()).decode("ascii")
            self._publish("frame", {"jpeg": b64})
        except Exception:
            pass

    # -- main entry ------------------------------------------------------

    def run(self) -> None:
        cap = None
        try:
            self._publish("status", {
                "state": "opening",
                "message": "Opening capture device...",
            })
            keep_alive = self._on_cap_return is not None
            cap = CaptureSource(
                self._device,
                width=self._profile.width,
                height=self._profile.height,
                fps=self._profile.target_fps,
                backend=self._backend,
                _precap=self._precap,
                _keep_alive=keep_alive,
            )
            self._precap = None  # ownership transferred
            self._publish("status", {
                "state": "ready",
                "message": (
                    f"Device opened: {cap.actual_width}x{cap.actual_height}"
                    f" @ {cap.actual_fps:.0f} FPS"
                ),
            })

            with cap:
                dispatch = {
                    "fountain": self._run_fountain,
                    "sequential": self._run_sequential,
                }
                handler = dispatch.get(self._mode, self._run_auto)
                handler(cap)

            # Return the cap to the server for reuse
            if self._on_cap_return is not None:
                raw = cap.detach()
                if raw is not None and raw.isOpened():
                    self._on_cap_return(raw)
        except Exception as exc:
            self._publish("error", {"message": str(exc)})

    # -- fountain mode ---------------------------------------------------

    def _run_fountain(self, cap: CaptureSource) -> None:
        protocol = get_protocol("fountain", profile=self._profile)
        decoder: FountainDecoder | None = None
        start_time: float | None = None
        bytes_received = 0
        frames_captured = 0
        last_progress = 0.0

        self._publish("status", {
            "state": "waiting",
            "message": "Waiting for fountain droplets...",
        })

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            frames_captured += 1

            # Preview every ~30 frames
            if frames_captured % 30 == 1:
                self._publish_preview(frame)

            frame = self._ensure_size(frame)
            sampled = sample_frame(
                frame, self._profile.rows,
                self._profile.cols, self._profile.block_size,
            )
            result = protocol.decode_frame(sampled)

            if not result.is_valid or result.data is None:
                continue

            seed, K, payload = result.frame_index, result.total_frames, result.data
            if K is None or K == 0 or K > 60000:
                continue

            if decoder is None:
                decoder = FountainDecoder(K, len(payload))
                start_time = time.time()
                self._publish("status", {
                    "state": "receiving",
                    "message": f"Transmission detected! K={K} chunks",
                    "total_chunks": K,
                })

            if decoder.K != K:
                continue

            decoder.add_droplet(seed, payload)
            bytes_received += len(payload)

            now = time.time()
            if now - last_progress > 0.1:
                last_progress = now
                self._publish_fountain_progress(
                    decoder, K, payload, bytes_received,
                    frames_captured, start_time,
                )

            if decoder.is_complete():
                self._finalize_fountain(
                    decoder, start_time, frames_captured, bytes_received,
                )
                return

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": frames_captured,
        })

    def _publish_fountain_progress(
        self, decoder, K, payload, bytes_received,
        frames_captured, start_time,
    ) -> None:
        elapsed = time.time() - start_time if start_time else 0
        speed = bytes_received / elapsed if elapsed > 2 else 0
        remaining = (K - len(decoder.chunks)) * len(payload)
        eta = remaining / speed if speed > 0 else -1

        self._publish("progress", {
            "chunks_decoded": len(decoder.chunks),
            "total_chunks": K,
            "percent": round(len(decoder.chunks) / K * 100, 1),
            "speed_kbps": round(speed / 1024, 1) if speed > 0 else 0,
            "eta_seconds": round(eta, 1) if eta >= 0 else -1,
            "frames_captured": frames_captured,
            "bytes_received": bytes_received,
            "decoded_indices": sorted(decoder.chunks.keys()),
        })

    def _finalize_fountain(
        self, decoder, start_time, frames_captured, bytes_received,
    ) -> None:
        full_data = decoder.get_file_data()
        file_size, expected_sha256, filename, content_offset = (
            parse_fountain_metadata(full_data)
        )

        if file_size is not None and filename is not None:
            file_content = bytes(
                full_data[content_offset:content_offset + file_size],
            )
            sha256_ok = bool(
                expected_sha256 and verify_integrity(file_content, expected_sha256),
            )
        else:
            file_content = bytes(full_data)
            filename = f"received_{int(time.time())}.bin"
            file_size = len(file_content)
            sha256_ok = False

        save_path = write_output(file_content, filename, self._output_dir)
        duration = time.time() - start_time if start_time else 0
        speed_mbps = (file_size * 8) / duration / 1_000_000 if duration > 0 else 0

        self._publish("complete", {
            "filename": filename,
            "size": file_size,
            "sha256_ok": sha256_ok,
            "save_path": save_path,
            "download_url": f"/api/receive/download/{filename}",
            "duration_s": round(duration, 2),
            "speed_mbps": round(speed_mbps, 2),
            "frames_captured": frames_captured,
            "bytes_received": bytes_received,
        })

    # -- sequential mode -------------------------------------------------

    def _run_sequential(self, cap: CaptureSource) -> None:
        protocol = get_protocol("sequential", profile=self._profile)
        received: dict[int, bytes] = {}
        expected_sha256: bytes | None = None
        expected_size: int | None = None
        expected_name: str | None = None
        total_expected: int | None = None
        start_time = time.time()
        frames_captured = 0
        bytes_received = 0
        last_progress = 0.0

        self._publish("status", {
            "state": "waiting",
            "message": "Waiting for sequential frames...",
        })

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            frames_captured += 1

            # Preview every ~30 frames
            if frames_captured % 30 == 1:
                self._publish_preview(frame)

            frame = self._ensure_size(frame)
            sampled = sample_frame(
                frame, self._profile.rows,
                self._profile.cols, self._profile.block_size,
            )
            result = protocol.decode_frame(sampled)

            if not result.is_valid:
                continue

            ftype, data = result.frame_type, result.data
            idx, total = result.frame_index, result.total_frames

            if ftype == FRAME_TYPE_START and expected_name is None:
                fs, sha, fn = parse_start_metadata(data)
                if fs is not None:
                    expected_size, expected_sha256, expected_name = fs, sha, fn
                    total_expected = total
                    self._publish("status", {
                        "state": "receiving",
                        "message": f"File: {fn} ({fs} bytes, {total} frames)",
                        "total_chunks": total,
                    })

            elif ftype == FRAME_TYPE_DATA:
                if total_expected is None and total:
                    total_expected = total
                if idx not in received:
                    received[idx] = data
                    bytes_received += len(data)
                now = time.time()
                if total_expected and now - last_progress > 0.1:
                    last_progress = now
                    self._publish("progress", {
                        "chunks_decoded": len(received),
                        "total_chunks": total_expected,
                        "percent": round(len(received) / total_expected * 100, 1),
                        "speed_kbps": round(
                            bytes_received / (now - start_time) / 1024, 1,
                        ) if now - start_time > 2 else 0,
                        "eta_seconds": -1,
                        "frames_captured": frames_captured,
                        "bytes_received": bytes_received,
                        "decoded_indices": sorted(received.keys()),
                    })

            elif ftype == FRAME_TYPE_END:
                if total_expected and len(received) >= total_expected:
                    self._finalize_sequential(
                        received, total_expected, expected_size,
                        expected_sha256, expected_name,
                        start_time, frames_captured, bytes_received,
                    )
                    return

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": frames_captured,
        })

    def _finalize_sequential(
        self, received, total_frames, expected_size,
        expected_sha256, expected_name,
        start_time, frames_captured, bytes_received,
    ) -> None:
        bpf = self._profile.seq_bytes_per_frame
        full_data = bytearray()
        for i in range(total_frames):
            full_data.extend(received.get(i, b"\x00" * bpf))

        if expected_size:
            file_content = bytes(full_data[:expected_size])
        else:
            file_content = bytes(full_data)

        sha256_ok = bool(
            expected_sha256 and verify_integrity(file_content, expected_sha256),
        )
        filename = expected_name or f"received_{int(time.time())}.bin"
        save_path = write_output(file_content, filename, self._output_dir)
        duration = time.time() - start_time
        speed_mbps = (len(file_content) * 8) / duration / 1e6 if duration > 0 else 0

        self._publish("complete", {
            "filename": filename,
            "size": len(file_content),
            "sha256_ok": sha256_ok,
            "save_path": save_path,
            "download_url": f"/api/receive/download/{filename}",
            "duration_s": round(duration, 2),
            "speed_mbps": round(speed_mbps, 2),
            "frames_captured": frames_captured,
            "bytes_received": bytes_received,
        })

    # -- auto-detect mode ------------------------------------------------

    def _run_auto(self, cap: CaptureSource) -> None:
        seq = get_protocol("sequential", profile=self._profile)
        fount = get_protocol("fountain", profile=self._profile)

        self._publish("status", {
            "state": "probing",
            "message": "Auto-detecting protocol...",
        })

        auto_frames = 0
        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            auto_frames += 1
            if auto_frames % 30 == 1:
                self._publish_preview(frame)

            frame = self._ensure_size(frame)
            sampled = sample_frame(
                frame, self._profile.rows,
                self._profile.cols, self._profile.block_size,
            )

            sr = seq.decode_frame(sampled)
            fr = fount.decode_frame(sampled)

            if sr.is_valid:
                self._publish("status", {
                    "state": "detected",
                    "message": "Sequential protocol detected",
                })
                self._run_sequential(cap)
                return

            if fr.is_valid:
                self._publish("status", {
                    "state": "detected",
                    "message": "Fountain protocol detected",
                })
                self._run_fountain(cap)
                return

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": 0,
        })

    # -- helpers ---------------------------------------------------------

    def _ensure_size(self, frame):
        if (frame.shape[0] != self._profile.height
                or frame.shape[1] != self._profile.width):
            return cv2.resize(frame, (self._profile.width, self._profile.height))
        return frame
