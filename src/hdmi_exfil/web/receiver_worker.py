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

from hdmi_exfil.application.preflight import is_preflight_start_result
from hdmi_exfil.application.receive_geometry import (
    build_geometry_candidates,
    decode_with_sampling_fallbacks,
    ensure_frame_size,
    estimate_sampling_from_frame,
    sample_grid,
)
from hdmi_exfil.application.receive_session import ReceiveSession
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


class _CaptureFallbackRequested(RuntimeError):
    """Internal control-flow exception used to retry another capture target."""


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
        fallback_targets: list[tuple[int, int | None]] | None = None,
        require_preflight: bool = False,
    ) -> None:
        super().__init__(daemon=True)
        self._device = device
        self._profile = profile
        self._mode = mode
        self._output_dir = output_dir
        self._backend = backend
        self._precap = precap
        self._on_cap_return = on_cap_return
        self._capture_targets = [(int(device), backend)]
        for source, alt_backend in fallback_targets or []:
            candidate = (int(source), alt_backend)
            if candidate not in self._capture_targets:
                self._capture_targets.append(candidate)
        self._active_device = int(device)
        self._active_backend = backend
        self._fallback_targets: list[tuple[int, int | None]] = []
        self._require_preflight = bool(require_preflight)
        self._stop_event = threading.Event()
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._runtime_state: dict[str, object] = {
            "state": "idle",
            "message": "",
            "protocol": None,
            "preflight_required": self._require_preflight,
            "preflight_state": "waiting" if self._require_preflight else "disabled",
            "active_device": self._active_device,
            "active_backend": self._active_backend,
        }
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
        self._mirror_runtime_state(event_type, data)
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

    def get_runtime_state(self) -> dict[str, object]:
        """Return the latest lightweight runtime state for web polling."""
        with self._lock:
            return dict(self._runtime_state)

    # -- main entry ------------------------------------------------------

    def run(self) -> None:
        pending_targets = list(self._capture_targets)

        while pending_targets and not self._stop_event.is_set():
            device, backend = pending_targets[0]
            self._active_device = device
            self._active_backend = backend
            self._fallback_targets = list(pending_targets[1:])
            self._set_runtime_state(
                active_device=device,
                active_backend=backend,
            )

            try:
                self._publish("status", {
                    "state": "opening",
                    "message": "Opening capture device...",
                })
                keep_alive = self._on_cap_return is not None and len(pending_targets) == 1
                cap = CaptureSource(
                    device,
                    width=self._profile.width,
                    height=self._profile.height,
                    fps=self._profile.target_fps,
                    backend=backend,
                    _precap=self._precap,
                    _keep_alive=keep_alive,
                )
                self._precap = None
                self._publish("status", {
                    "state": "ready",
                    "message": (
                        f"Device opened: {cap.actual_width}x{cap.actual_height}"
                        f" @ {cap.actual_fps:.0f} FPS"
                    ),
                })

                with cap:
                    if self._require_preflight and not self._wait_for_preflight(cap):
                        return
                    dispatch = {
                        "fountain": self._run_fountain,
                        "sequential": self._run_sequential,
                    }
                    handler = dispatch.get(self._mode, self._run_auto)
                    handler(cap)

                if keep_alive and self._on_cap_return is not None:
                    raw = cap.detach()
                    if raw is not None and raw.isOpened():
                        self._on_cap_return(raw)
                return
            except _CaptureFallbackRequested:
                pending_targets = pending_targets[1:]
                self._precap = None
                continue
            except Exception as exc:
                pending_targets = pending_targets[1:]
                self._precap = None
                if pending_targets:
                    self._publish("status", {
                        "state": "fallback",
                        "message": (
                            f"{exc} Retrying alternate capture target "
                            f"({self._describe_capture_target(*pending_targets[0])})."
                        ),
                    })
                    continue
                self._publish("error", {"message": str(exc)})
                break
            finally:
                with self._preview_condition:
                    self._preview_condition.notify_all()

    # -- fountain mode ---------------------------------------------------

    def _wait_for_preflight(self, cap: CaptureSource) -> bool:
        selected_bpc = int(self._profile.bits_per_channel)
        candidate_bpcs = [selected_bpc] + [b for b in (1, 2, 3) if b != selected_bpc]
        probe_candidates: list[tuple[int, ResolutionProfile, object]] = []
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
            ))

        frames_captured = 0
        low_signal_streak = 0
        last_waiting_emit = 0.0
        geometry_candidates = self._build_geometry_candidates(self._profile)
        geometry_cursor = 0

        self._publish("status", {
            "state": "preflight_wait",
            "message": "Waiting for HDMI preflight frame...",
            "preflight_required": True,
            "preflight_state": "waiting",
        })

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue

            frames_captured += 1
            self._maybe_publish_preview(frame)
            low_signal_streak = self._update_low_signal_streak(frame, low_signal_streak)

            now = time.time()
            if (now - last_waiting_emit) >= 1.0:
                last_waiting_emit = now
                self._publish("status", {
                    "state": "preflight_wait",
                    "message": (
                        "Waiting for HDMI preflight frame... "
                        f"({frames_captured:,} frames scanned)"
                    ),
                    "frames_captured": frames_captured,
                    "preflight_required": True,
                    "preflight_state": "waiting",
                })

            frame = self._ensure_size(frame)
            for bpc, profile, protocol in probe_candidates:
                result, geometry_cursor, _ = self._decode_with_sampling_fallbacks(
                    frame,
                    profile,
                    protocol.decode_frame,
                    geometry_candidates,
                    geometry_cursor,
                )
                if result is None or not result.is_valid:
                    continue
                if not is_preflight_start_result(result):
                    continue
                low_signal_streak = 0
                self._profile = profile
                self._publish("status", {
                    "state": "preflight_ok",
                    "message": self._preflight_detected_message(
                        selected_bpc=selected_bpc,
                        detected_bpc=bpc,
                        sampling=self._sampling,
                    ),
                    "frames_captured": frames_captured,
                    "preflight_required": True,
                    "preflight_state": "ok",
                })
                return True

            self._maybe_request_runtime_fallback(
                protocol_name="preflight",
                frames_captured=frames_captured,
                has_progress=False,
                low_signal_streak=low_signal_streak,
            )

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": frames_captured,
        })
        return False

    def _run_fountain(self, cap: CaptureSource) -> None:
        protocol = get_protocol("fountain", profile=self._profile)
        session = ReceiveSession(mode="fountain", profile=self._profile)
        frames_captured = 0
        low_signal_streak = 0
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
            low_signal_streak = self._update_low_signal_streak(frame, low_signal_streak)

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
                self._maybe_request_runtime_fallback(
                    protocol_name="fountain",
                    frames_captured=frames_captured,
                    has_progress=session._fountain_decoder is not None,
                    low_signal_streak=low_signal_streak,
                )
                continue

            low_signal_streak = 0
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
        low_signal_streak = 0
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
            low_signal_streak = self._update_low_signal_streak(frame, low_signal_streak)

            frame = self._ensure_size(frame)
            result, geometry_cursor, _ = self._decode_with_sampling_fallbacks(
                frame,
                self._profile,
                protocol.decode_frame,
                geometry_candidates,
                geometry_cursor,
            )

            if result is None or not result.is_valid:
                self._maybe_request_runtime_fallback(
                    protocol_name="sequential",
                    frames_captured=frames_captured,
                    has_progress=(
                        session._seq_saw_start
                        or session._seq_saw_end
                        or session._seq_total_expected is not None
                        or bool(session._seq_received)
                    ),
                    low_signal_streak=low_signal_streak,
                )
                continue
            if is_preflight_start_result(result):
                continue

            low_signal_streak = 0
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

            self._maybe_request_runtime_fallback(
                protocol_name="auto",
                frames_captured=frames_probed,
                has_progress=False,
                low_signal_streak=black_streak,
            )

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
                        if is_preflight_start_result(sr):
                            continue
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
        return ensure_frame_size(frame, self._profile)

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
        result, geometry_cursor, matched_sampling = decode_with_sampling_fallbacks(
            frame,
            profile,
            decode_frame,
            self._sampling,
            geometry_candidates,
            geometry_cursor,
            extra_candidates=extra_candidates,
        )
        if matched_sampling is not None:
            self._sampling = matched_sampling
        return result, geometry_cursor, matched_sampling

    def _sample_grid(
        self,
        frame,
        profile: ResolutionProfile,
        sampling: tuple[int, int, float, float] | None = None,
    ):
        return sample_grid(frame, profile, sampling or self._sampling)

    def _build_geometry_candidates(
        self,
        profile: ResolutionProfile,
    ) -> list[tuple[int, int, float, float]]:
        return build_geometry_candidates(profile)

    def _estimate_sampling_from_frame(
        self,
        frame,
        profile: ResolutionProfile,
    ) -> tuple[int, int, float, float] | None:
        return estimate_sampling_from_frame(frame, profile)

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

    def _preflight_detected_message(
        self,
        *,
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
                "HDMI preflight detected on capture path "
                f"(bpc={detected_bpc}) — switching from bpc={selected_bpc}"
                f"{geom_suffix}"
            )
        return f"HDMI preflight detected on capture path (bpc={detected_bpc}){geom_suffix}"

    def _update_low_signal_streak(self, frame, streak: int) -> int:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if float(gray.mean()) < 3.0 and float(gray.std()) < 2.0:
            return streak + 1
        return 0

    def _maybe_request_runtime_fallback(
        self,
        *,
        protocol_name: str,
        frames_captured: int,
        has_progress: bool,
        low_signal_streak: int,
    ) -> None:
        if self._active_backend != cv2.CAP_DSHOW or not self._fallback_targets:
            return
        if has_progress:
            return
        if low_signal_streak >= 120:
            self._request_capture_fallback(
                "Current DSHOW source is black or low-signal.",
            )
        if frames_captured >= 360:
            self._request_capture_fallback(
                f"No decodable {protocol_name} frames found on current DSHOW source.",
            )

    def _request_capture_fallback(self, reason: str) -> None:
        if not self._fallback_targets:
            return
        next_device, next_backend = self._fallback_targets[0]
        self._publish("status", {
            "state": "fallback",
            "message": (
                f"{reason} Retrying alternate capture target "
                f"({self._describe_capture_target(next_device, next_backend)})."
            ),
        })
        raise _CaptureFallbackRequested(reason)

    def _describe_capture_target(self, device: int, backend: int | None) -> str:
        if backend == cv2.CAP_DSHOW:
            return f"source {device} via DSHOW"
        if backend == cv2.CAP_MSMF:
            return f"source {device} via MSMF"
        if backend is None:
            return f"source {device}"
        return f"source {device} via backend {backend}"

    def _set_runtime_state(self, **kwargs: object) -> None:
        with self._lock:
            self._runtime_state.update(kwargs)

    def _mirror_runtime_state(self, event_type: str, data: dict) -> None:
        updates: dict[str, object] = {
            "preflight_required": self._require_preflight,
            "active_device": self._active_device,
            "active_backend": self._active_backend,
        }
        if event_type == "status":
            updates.update(data)
            updates.setdefault(
                "preflight_state",
                self._runtime_state.get("preflight_state", "disabled"),
            )
        elif event_type == "complete":
            updates.update({
                "state": "complete",
                "message": f"Complete: {data.get('filename', 'output')}",
                "protocol": data.get("protocol"),
            })
        elif event_type == "error":
            updates.update({
                "state": "error",
                "message": data.get("message", "Error"),
            })
        elif event_type == "stopped":
            updates.update({
                "state": "stopped",
                "message": data.get("message", "Stopped"),
            })
        self._set_runtime_state(**updates)
