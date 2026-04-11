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

import contextlib
from dataclasses import replace
import queue
import threading
import time

import cv2
import numpy as np

from hdmi_exfil.application.receive_session import ReceiveSession
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
        # Latest frame for MJPEG preview stream
        self._preview_frame: bytes | None = None
        self._preview_condition = threading.Condition()
        self._preview_seq = 0
        self._preview_quality = 75
        self._preview_scale = 1.0  # 1.0 = native
        self._preview_target_fps = 30.0
        self._preview_last_publish = 0.0
        self._preview_last_frame_monotonic = 0.0
        # Sampling geometry for letterboxed/scaled browser output.
        # (offset_x, offset_y, scale_x, scale_y)
        self._sampling: tuple[int, int, float, float] = (0, 0, 1.0, 1.0)

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
        with self._preview_condition:
            self._preview_condition.notify_all()
        self.join(timeout=5.0)

    # -- preview ---------------------------------------------------------

    def _publish_preview(self, frame) -> None:
        """Encode frame as JPEG and store the latest preview image."""
        try:
            scale = self._preview_scale
            if scale < 1.0:
                h, w = frame.shape[:2]
                new_w, new_h = int(w * scale), int(h * scale)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
            ok, jpeg = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._preview_quality],
            )
            if not ok:
                return
            with self._preview_condition:
                self._preview_frame = jpeg.tobytes()
                self._preview_seq += 1
                self._preview_last_frame_monotonic = time.monotonic()
                self._preview_condition.notify_all()
        except Exception:
            pass

    def _maybe_publish_preview(self, frame) -> None:
        """Publish preview frames at a bounded rate while keeping low latency."""
        target_fps = self._preview_target_fps
        if target_fps > 0:
            now = time.perf_counter()
            interval = 1.0 / target_fps
            if now - self._preview_last_publish < interval:
                return
            self._preview_last_publish = now
        self._publish_preview(frame)

    def wait_for_preview(
        self,
        last_seq: int,
        timeout_s: float = 1.0,
    ) -> tuple[bytes | None, int]:
        """Block until a new preview frame is ready or timeout expires."""
        with self._preview_condition:
            if self._preview_seq <= last_seq and not self._stop_event.is_set():
                self._preview_condition.wait(timeout=timeout_s)
            return self._preview_frame, self._preview_seq

    def get_preview_health(self) -> dict[str, float | int | None]:
        """Return lightweight preview heartbeat metrics for web status polling."""
        with self._preview_condition:
            seq = self._preview_seq
            last_frame = self._preview_last_frame_monotonic
        age_s: float | None = None
        if last_frame > 0.0:
            age_s = max(0.0, time.monotonic() - last_frame)
        return {
            "preview_seq": seq,
            "preview_age_s": age_s,
        }

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
        finally:
            with self._preview_condition:
                self._preview_condition.notify_all()

    # -- fountain mode ---------------------------------------------------

    def _run_fountain(self, cap: CaptureSource) -> None:
        protocol = get_protocol("fountain", profile=self._profile)
        session = ReceiveSession(mode="fountain", profile=self._profile)
        frames_captured = 0
        last_progress = 0.0
        last_waiting_emit = 0.0
        geometry_candidates = self._build_geometry_candidates(self._profile)
        geometry_cursor = 0

        self._publish("status", {
            "state": "waiting",
            "message": "Waiting for fountain droplets...",
            "protocol": "fountain",
        })

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            frames_captured += 1

            self._maybe_publish_preview(frame)

            now = time.time()
            if session.detected_protocol is None and (now - last_waiting_emit) >= 1.0:
                last_waiting_emit = now
                self._publish("status", {
                    "state": "waiting",
                    "message": (
                        "Waiting for fountain droplets... "
                        f"({frames_captured:,} frames scanned)"
                    ),
                    "frames_captured": frames_captured,
                    "protocol": "fountain",
                })

            frame = self._ensure_size(frame)
            result, geometry_cursor, _ = self._decode_with_sampling_fallbacks(
                frame,
                self._profile,
                protocol.decode_frame,
                geometry_candidates,
                geometry_cursor,
            )

            if result is None or not result.is_valid or result.data is None:
                continue

            events = session.feed_frame_result("fountain", result)
            for event in events:
                data = dict(event.data)
                data["frames_captured"] = frames_captured

                if event.kind == "status":
                    self._publish("status", data)
                    continue

                if event.kind == "progress":
                    if now - last_progress > 0.2:
                        last_progress = now
                        self._publish("progress", data)
                    continue

                file_content = bytes(data.pop("file_content"))
                filename = str(data["filename"])
                save_path = write_output(file_content, filename, self._output_dir)
                data["save_path"] = save_path
                data["download_url"] = f"/api/receive/download/{filename}"
                self._publish("complete", data)
                return

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": frames_captured,
        })

    def _publish_fountain_progress(
        self, decoder, K, payload, bytes_received,
        droplets_received, unique_droplets_received, expected_droplets,
        frames_captured, start_time,
        *,
        emit_indices: bool = True,
    ) -> None:
        decoded = len(decoder.chunks)
        unknown = max(0, K - decoded)
        # Fountain decoding is non-linear: BP/GE can unlock many chunks at once.
        # Use unresolved equation count as a progress hint for smoother, more
        # realistic ETA/percent while keeping Solved/Needed exact.
        unresolved = sum(1 for d in decoder.droplets if len(d[0]) > 0)
        hinted = decoded + min(unknown, int(unresolved * 0.8))
        effective_resolved = max(decoded, min(K, hinted))

        elapsed = time.time() - start_time if start_time else 0
        speed = bytes_received / elapsed if elapsed > 2 else 0
        remaining = max(0, K - effective_resolved) * len(payload)
        eta = remaining / speed if speed > 0 else -1
        percent = round(decoded / K * 100, 1)
        # Keep 100% exclusively for the "complete" event to avoid
        # transient UI jumps when late progress and completion race.
        if percent >= 100.0:
            percent = 99.9
        acquisition_percent = round((droplets_received / K) * 100, 1)

        data = {
            "protocol": "fountain",
            "chunks_decoded": decoded,
            "total_chunks": K,
            "percent": percent,
            "droplets_received": droplets_received,
            "unique_droplets_received": unique_droplets_received,
            "expected_droplets": expected_droplets,
            "acquisition_percent": acquisition_percent,
            "speed_kbps": round(speed / 1024, 1) if speed > 0 else 0,
            "eta_seconds": round(eta, 1) if eta >= 0 else -1,
            "frames_captured": frames_captured,
            "bytes_received": bytes_received,
        }
        if emit_indices:
            data["decoded_indices"] = sorted(decoder.chunks.keys())
        self._publish("progress", data)

    def _finalize_fountain(
        self, decoder, start_time, frames_captured, bytes_received,
        droplets_received, unique_droplets_received, expected_droplets,
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
            "protocol": "fountain",
            "filename": filename,
            "size": file_size,
            "sha256_ok": sha256_ok,
            "sha256_available": expected_sha256 is not None,
            "save_path": save_path,
            "download_url": f"/api/receive/download/{filename}",
            "duration_s": round(duration, 2),
            "speed_mbps": round(speed_mbps, 2),
            "frames_captured": frames_captured,
            "bytes_received": bytes_received,
            "droplets_received": droplets_received,
            "unique_droplets_received": unique_droplets_received,
            "expected_droplets": expected_droplets,
            "chunks_decoded": len(decoder.chunks),
            "total_chunks": decoder.K,
        })

    # -- sequential mode -------------------------------------------------

    def _run_sequential(self, cap: CaptureSource) -> None:
        protocol = get_protocol("sequential", profile=self._profile)
        session = ReceiveSession(mode="sequential", profile=self._profile)
        frames_captured = 0
        geometry_candidates = self._build_geometry_candidates(self._profile)
        geometry_cursor = 0

        self._publish("status", {
            "state": "waiting",
            "message": "Waiting for sequential frames...",
            "protocol": "sequential",
        })

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            frames_captured += 1

            self._maybe_publish_preview(frame)

            frame = self._ensure_size(frame)
            result, geometry_cursor, _ = self._decode_with_sampling_fallbacks(
                frame,
                self._profile,
                protocol.decode_frame,
                geometry_candidates,
                geometry_cursor,
            )

            if result is None or not result.is_valid:
                continue

            events = session.feed_frame_result("sequential", result)
            for event in events:
                data = dict(event.data)
                data["frames_captured"] = frames_captured

                if event.kind in {"status", "progress"}:
                    self._publish(event.kind, data)
                    continue

                file_content = bytes(data.pop("file_content"))
                filename = str(data["filename"])
                save_path = write_output(file_content, filename, self._output_dir)
                data["save_path"] = save_path
                data["download_url"] = f"/api/receive/download/{filename}"
                self._publish("complete", data)
                return

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": frames_captured,
        })

    def _reassemble_sequential_data(
        self,
        received: dict[int, bytes],
        total_frames: int,
    ) -> tuple[bytes, list[int]]:
        bpf = self._profile.seq_bytes_per_frame
        full_data = bytearray()
        missing: list[int] = []
        for i in range(total_frames):
            chunk = received.get(i)
            if chunk is None:
                missing.append(i)
                full_data.extend(b"\x00" * bpf)
            else:
                full_data.extend(chunk)
        return bytes(full_data), missing

    def _finalize_sequential(
        self, received, total_frames, expected_size,
        expected_sha256, expected_name,
        start_time, frames_captured, bytes_received,
        *,
        saw_start: bool,
        saw_end: bool,
        pass_count: int,
    ) -> None:
        full_data, missing = self._reassemble_sequential_data(received, total_frames)

        if expected_size is not None:
            file_content = full_data[:expected_size]
        else:
            file_content = full_data

        sha256_ok = bool(
            expected_sha256 and verify_integrity(file_content, expected_sha256),
        )
        filename = expected_name or f"received_{int(time.time())}.bin"
        save_path = write_output(file_content, filename, self._output_dir)
        duration = time.time() - start_time
        speed_mbps = (len(file_content) * 8) / duration / 1e6 if duration > 0 else 0

        self._publish("complete", {
            "protocol": "sequential",
            "filename": filename,
            "size": len(file_content),
            "sha256_ok": sha256_ok,
            "sha256_available": expected_sha256 is not None,
            "save_path": save_path,
            "download_url": f"/api/receive/download/{filename}",
            "duration_s": round(duration, 2),
            "speed_mbps": round(speed_mbps, 2),
            "frames_captured": frames_captured,
            "bytes_received": bytes_received,
            "chunks_decoded": len(received),
            "total_chunks": total_frames,
            "start_seen": saw_start,
            "end_seen": saw_end,
            "pass_count": pass_count,
            "missing_frames": missing,
        })

    # -- auto-detect mode ------------------------------------------------

    def _run_auto(self, cap: CaptureSource) -> None:
        selected_bpc = int(self._profile.bits_per_channel)
        candidate_bpcs = [selected_bpc] + [b for b in (1, 2, 3) if b != selected_bpc]
        probe_candidates: list[tuple[int, ResolutionProfile, object, object]] = []
        for bpc in candidate_bpcs:
            profile = (
                self._profile
                if bpc == selected_bpc
                else replace(self._profile, bits_per_channel=bpc)
            )
            probe_candidates.append((
                bpc,
                profile,
                get_protocol("sequential", profile=profile),
                get_protocol("fountain", profile=profile),
            ))
        geometry_candidates = self._build_geometry_candidates(self._profile)
        geometry_cursor = 0

        self._publish("status", {
            "state": "probing",
            "message": "Auto-detecting protocol and bpc...",
        })

        frames_probed = 0
        black_streak = 0
        no_signal_reported = False
        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue
            frames_probed += 1

            self._maybe_publish_preview(frame)

            frame = self._ensure_size(frame)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if float(gray.mean()) < 1.5 and float(gray.std()) < 1.0:
                black_streak += 1
                if black_streak >= 90 and not no_signal_reported:
                    no_signal_reported = True
                    self._publish("status", {
                        "state": "no_signal",
                        "message": (
                            "No video signal detected (black frames). "
                            "Check Elgato source/duplication."
                        ),
                    })
            else:
                black_streak = 0
                if no_signal_reported:
                    no_signal_reported = False
                    self._publish("status", {
                        "state": "probing",
                        "message": "Signal restored. Auto-detecting protocol and bpc...",
                    })

            # Keep per-frame probing bounded: identity + a rotating subset of
            # alternate geometry candidates.
            batch = [geometry_candidates[0]]
            dynamic_sampling = self._estimate_sampling_from_frame(frame, self._profile)
            if dynamic_sampling is not None:
                batch.append(dynamic_sampling)
            if len(geometry_candidates) > 1:
                for _ in range(5):
                    geometry_cursor = (geometry_cursor + 1) % len(geometry_candidates)
                    if geometry_cursor == 0:
                        geometry_cursor = 1
                    batch.append(geometry_candidates[geometry_cursor])

            for sampling in batch:
                for bpc, profile, seq, fount in probe_candidates:
                    sampled = self._sample_grid(frame, profile, sampling=sampling)

                    sr = seq.decode_frame(sampled)
                    if sr.is_valid:
                        self._sampling = sampling
                        self._profile = profile
                        self._publish("status", {
                            "state": "detected",
                            "message": self._detected_message(
                                protocol_name="Sequential",
                                selected_bpc=selected_bpc,
                                detected_bpc=bpc,
                                sampling=sampling,
                            ),
                            "protocol": "sequential",
                        })
                        self._run_sequential(cap)
                        return

                    fr = fount.decode_frame(sampled)
                    if fr.is_valid:
                        self._sampling = sampling
                        self._profile = profile
                        self._publish("status", {
                            "state": "detected",
                            "message": self._detected_message(
                                protocol_name="Fountain",
                                selected_bpc=selected_bpc,
                                detected_bpc=bpc,
                                sampling=sampling,
                            ),
                            "protocol": "fountain",
                        })
                        self._run_fountain(cap)
                        return

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": frames_probed,
        })

    # -- helpers ---------------------------------------------------------

    def _ensure_size(self, frame):
        if (frame.shape[0] != self._profile.height
                or frame.shape[1] != self._profile.width):
            # Nearest-neighbor keeps block symbols stable for 2/3 bpc decoding.
            return cv2.resize(
                frame,
                (self._profile.width, self._profile.height),
                interpolation=cv2.INTER_NEAREST,
            )
        return frame

    def _decode_with_sampling_fallbacks(
        self,
        frame,
        profile: ResolutionProfile,
        decode_frame,
        geometry_candidates: list[tuple[int, int, float, float]],
        geometry_cursor: int,
        *,
        extra_candidates: int = 5,
    ):
        """Try the current sampling first, then probe browser-style fallbacks.

        Manual Web UI modes need the same geometry resilience as auto-detect:
        browser fullscreen can still leave slight viewport offsets/scales that
        make exact block-centre sampling miss valid frames.
        """
        batch: list[tuple[int, int, float, float]] = []
        seen: set[tuple[int, int, float, float]] = set()

        def add(sampling: tuple[int, int, float, float]) -> None:
            key = (
                int(sampling[0]),
                int(sampling[1]),
                round(float(sampling[2]), 6),
                round(float(sampling[3]), 6),
            )
            if key in seen:
                return
            seen.add(key)
            batch.append(sampling)

        add(self._sampling)
        add((0, 0, 1.0, 1.0))

        dynamic_sampling = self._estimate_sampling_from_frame(frame, profile)
        if dynamic_sampling is not None:
            add(dynamic_sampling)

        if len(geometry_candidates) > 1:
            for _ in range(extra_candidates):
                geometry_cursor = (geometry_cursor + 1) % len(geometry_candidates)
                if geometry_cursor == 0:
                    geometry_cursor = 1
                add(geometry_candidates[geometry_cursor])

        for sampling in batch:
            sampled = self._sample_grid(frame, profile, sampling=sampling)
            result = decode_frame(sampled)
            if getattr(result, "is_valid", False):
                self._sampling = sampling
                return result, geometry_cursor, sampling

        return None, geometry_cursor, None

    def _sample_grid(
        self,
        frame,
        profile: ResolutionProfile,
        sampling: tuple[int, int, float, float] | None = None,
    ):
        offset_x, offset_y, scale_x, scale_y = sampling or self._sampling
        return sample_frame(
            frame,
            profile.rows,
            profile.cols,
            profile.block_size,
            offset_x=offset_x,
            offset_y=offset_y,
            scale_x=scale_x,
            scale_y=scale_y,
        )

    def _build_geometry_candidates(
        self,
        profile: ResolutionProfile,
    ) -> list[tuple[int, int, float, float]]:
        width = int(profile.width)
        height = int(profile.height)
        candidates: list[tuple[int, int, float, float]] = [(0, 0, 1.0, 1.0)]
        seen = {candidates[0]}

        def push(vw: int, vh: int, align_x: str, align_y: str) -> None:
            if vw <= 0 or vh <= 0:
                return
            sx = float(vw / width)
            sy = float(vh / height)
            ox = 0 if align_x == "left" else max(0, (width - vw) // 2)
            oy = 0 if align_y == "top" else max(0, (height - vh) // 2)
            key = (int(ox), int(oy), round(sx, 6), round(sy, 6))
            if key in seen:
                return
            seen.add(key)
            candidates.append((int(ox), int(oy), sx, sy))

        # Common browser/content-box reductions on 1080p outputs.
        h_candidates = [
            height - d
            for d in (8, 16, 24, 32, 40, 48, 52, 56, 64, 80, 96, 120, 128, 144, 147, 160, 180, 200)
        ]
        w_candidates = [width - d for d in (8, 16, 24, 32, 40, 64, 80, 96, 120, 160, 192)]

        for vh in h_candidates:
            push(width, vh, "left", "top")
            push(width, vh, "left", "center")

        for vw in w_candidates:
            push(vw, height, "left", "top")
            push(vw, height, "center", "top")

        # Typical combined reductions (both axes) when browser chrome remains.
        for vw in (width - 16, width - 24, width - 32, width - 64, width - 96):
            for vh in (height - 48, height - 52, height - 56, height - 64, height - 96, height - 120, height - 147):
                push(vw, vh, "center", "center")

        # Explicit viewport sizes seen in Chromium windows on 1080p displays.
        for vw, vh in ((1904, 933), (1904, 989), (1904, 1028), (1920, 1028), (1920, 1032)):
            push(vw, vh, "center", "center")

        return candidates

    def _estimate_sampling_from_frame(
        self,
        frame,
        profile: ResolutionProfile,
    ) -> tuple[int, int, float, float] | None:
        """Estimate active content area from frame variance.

        Browser/window borders are usually low-variance while the encoded HDMI
        grid has high spatial variance. This gives a robust fallback geometry
        when the sender is not perfectly fullscreen.
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            row_std = gray.std(axis=1)
            col_std = gray.std(axis=0)

            # Adaptive thresholds with conservative floor values.
            row_thr = max(6.0, float(np.percentile(row_std, 70) * 0.5))
            col_thr = max(6.0, float(np.percentile(col_std, 70) * 0.5))

            rows = np.where(row_std >= row_thr)[0]
            cols = np.where(col_std >= col_thr)[0]
            if rows.size == 0 or cols.size == 0:
                return None

            top = int(rows[0])
            bottom = int(rows[-1])
            left = int(cols[0])
            right = int(cols[-1])
            vh = max(1, bottom - top + 1)
            vw = max(1, right - left + 1)

            # Ignore implausibly small boxes (noise / random motion).
            if vh < int(profile.height * 0.55) or vw < int(profile.width * 0.55):
                return None

            sx = float(vw / profile.width)
            sy = float(vh / profile.height)
            return (left, top, sx, sy)
        except Exception:
            return None

    def _detected_message(
        self,
        protocol_name: str,
        selected_bpc: int,
        detected_bpc: int,
        sampling: tuple[int, int, float, float],
    ) -> str:
        ox, oy, sx, sy = sampling
        geom_suffix = ""
        if sampling != (0, 0, 1.0, 1.0):
            geom_suffix = (
                f" | geometry offset=({ox},{oy}) scale=({sx:.4f},{sy:.4f})"
            )
        if detected_bpc != selected_bpc:
            return (
                f"{protocol_name} protocol detected (bpc={detected_bpc}) "
                f"— switching from bpc={selected_bpc}{geom_suffix}"
            )
        return f"{protocol_name} protocol detected (bpc={detected_bpc}){geom_suffix}"
