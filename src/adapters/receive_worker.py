"""Shared background capture receiver used by CLI and web interfaces.

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

from hdmi_transfer.application.preflight import is_calibration_frame_valid, is_preflight_start_result
from hdmi_transfer.adapters.calibration_store import CalibrationStore, calibration_key
from hdmi_transfer.application.receive_geometry import (
    build_geometry_candidates,
    decode_with_sampling_fallbacks,
    ensure_frame_size,
    estimate_sampling_from_frame,
    sample_grid,
)
from hdmi_transfer.application.receive_session import ReceiveSession
from hdmi_transfer.core.config import (
    ResolutionProfile,
)
from hdmi_transfer.core.file_handling.writer import write_output
from hdmi_transfer.core.protocols import get_protocol
from hdmi_transfer.receiver.capture.source import CaptureSource


_LOW_SIGNAL_DETECTED_AFTER_S = 1.0
_RUNTIME_FALLBACK_LOW_SIGNAL_AFTER_S = 2.5
_RUNTIME_FALLBACK_NO_PROGRESS_AFTER_S = 6.0


class _CaptureFallbackRequested(RuntimeError):
    """Internal control-flow exception used to retry another capture target."""


class _FirstFrameCapture:
    """Replay the detection frame once before continuing the capture stream."""

    def __init__(self, frame, source):
        self._frame = frame
        self._source = source

    def read(self):
        if self._frame is not None:
            frame, self._frame = self._frame, None
            return True, frame
        return self._source.read()


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
        device: int | str,
        profile: ResolutionProfile,
        mode: str = "auto",
        output_dir: str = "received_files",
        backend: int | None = None,
        precap: "cv2.VideoCapture | None" = None,
        on_cap_return: "callable | None" = None,
        fallback_targets: list[tuple[int | str, int | None]] | None = None,
        require_preflight: bool = False,
        force_recalibration: bool = False,
        device_identity: str | None = None,
        calibration_store: CalibrationStore | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self._device = device
        self._profile = profile
        self._mode = mode
        self._output_dir = output_dir
        self._backend = backend
        self._precap = precap
        self._on_cap_return = on_cap_return
        self._restrict_runtime_fallback_to_dshow = (
            isinstance(device, str) and device.startswith("ffmpeg-dshow:")
        )
        self._capture_targets = [(device, backend)]
        ordered_fallbacks = list(fallback_targets or [])
        if self._restrict_runtime_fallback_to_dshow:
            ordered_fallbacks.sort(
                key=lambda candidate: 0 if candidate[1] == cv2.CAP_DSHOW else 1,
            )
        for source, alt_backend in ordered_fallbacks:
            candidate = (source, alt_backend)
            if candidate not in self._capture_targets:
                self._capture_targets.append(candidate)
        self._active_device = device
        self._active_backend = backend
        self._fallback_targets: list[tuple[int | str, int | None]] = []
        self._require_preflight = bool(require_preflight)
        self._force_recalibration = bool(force_recalibration)
        self._awaiting_payload = False
        self._calibration_protocol = None
        self._calibration_capture_shape: tuple[int, int] | None = None
        self._device_identity = device_identity or str(device)
        self._calibration_store = calibration_store or CalibrationStore()
        self._stop_event = threading.Event()
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._runtime_state: dict[str, object] = {
            "state": "idle",
            "message": "",
            "protocol": None,
            "preflight_required": self._require_preflight,
            "preflight_state": "waiting" if self._require_preflight else "disabled",
            "preflight_stage": "path" if self._require_preflight else "disabled",
            "requested_transfer_bpc": int(self._profile.bits_per_channel),
            "transfer_bpc": None,
            "calibration_state": "checking" if self._require_preflight else "disabled",
            "calibration_reused": False,
            "calibration_samples": 0,
            "active_device": self._active_device,
            "active_backend": self._active_backend,
        }
        # Latest frame for MJPEG preview stream
        self._preview_frame: bytes | None = None
        self._preview_condition = threading.Condition()
        self._preview_seq = 0
        self._preview_quality = 45
        self._preview_scale = 0.5
        self._preview_target_fps = 10.0
        self._preview_consumers = 0
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

    def add_preview_consumer(self) -> None:
        with self._preview_condition:
            self._preview_consumers += 1

    def remove_preview_consumer(self) -> None:
        with self._preview_condition:
            self._preview_consumers = max(0, self._preview_consumers - 1)

    def _maybe_publish_preview(self, frame) -> None:
        """Only encode preview images when a client actually consumes them."""
        with self._preview_condition:
            if self._preview_consumers <= 0:
                return
        target_fps = self._preview_target_fps
        if target_fps <= 0:
            return
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
        """Validate three distinct live calibration frames before receiving data.

        The sender emits calibration directly at the requested encoding. There
        is no ambiguous 1-bpc path stage. A stored geometry is only a first
        candidate: CRC-valid fresh frames must confirm it every time.
        """
        selected_bpc = int(self._profile.bits_per_channel)
        probe_candidates = []
        for bpc in [selected_bpc] + [b for b in (1, 2, 3) if b != selected_bpc]:
            profile = replace(self._profile, bits_per_channel=bpc)
            probe_candidates.append((bpc, profile, get_protocol("sequential", profile=profile)))
        geometry_candidates = self._build_geometry_candidates(self._profile)
        geometry_cursor = 0
        hints: dict[str, tuple[int, int, float, float] | None] = {}
        current: dict[str, tuple[int, int, float, float]] = {}
        stable_match = None
        unique_frames: set[int] = set()
        frames_captured = 0
        low_signal_streak = 0
        low_signal_since = None
        wait_started_at = time.time()
        last_waiting_emit = 0.0
        self._sampling = (0, 0, 1.0, 1.0)
        self._publish("status", {
            "state": "preflight_wait", "message": "Waiting for calibration signal...",
            "preflight_required": True, "preflight_state": "waiting",
            "preflight_stage": "transfer", "requested_transfer_bpc": selected_bpc,
            "transfer_bpc": None, "calibration_state": "checking",
            "calibration_reused": False, "calibration_samples": 0,
        })
        while not self._stop_event.is_set():
            ret, raw_frame = cap.read()
            if not ret:
                time.sleep(0.001)
                continue
            frames_captured += 1
            self._maybe_publish_preview(raw_frame)
            now = time.time()
            low_signal_streak, low_signal_since, low_signal_duration_s = self._update_low_signal_state(
                raw_frame, low_signal_streak, low_signal_since, now,
            )
            if now - last_waiting_emit >= 1.0:
                last_waiting_emit = now
                self._publish("status", {
                    "state": "preflight_wait", "message": "Checking calibration signal...",
                    "frames_captured": frames_captured,
                    "preflight_state": "waiting", "preflight_stage": "transfer",
                    "low_signal_streak": low_signal_streak,
                    "low_signal_duration_s": round(low_signal_duration_s, 2),
                    "low_signal_detected": self._is_low_signal_detected(low_signal_duration_s, low_signal_streak),
                })
            frame = self._ensure_size(raw_frame)
            matched = False
            for bpc, profile, protocol in probe_candidates:
                key = calibration_key(
                    device_identity=self._device_identity, open_device=self._active_device,
                    backend=self._active_backend, profile=profile,
                    capture_shape=raw_frame.shape,
                )
                if key not in hints:
                    hints[key] = None if self._force_recalibration else self._calibration_store.load(key)
                    current[key] = hints[key] or (0, 0, 1.0, 1.0)
                self._sampling = current[key]

                def decode_calibration(sampled):
                    decoded = protocol.decode_frame(sampled)
                    return decoded if is_calibration_frame_valid(sampled, profile, decoded) else None

                result, geometry_cursor, sampling = self._decode_with_sampling_fallbacks(
                    frame, profile, decode_calibration, geometry_candidates, geometry_cursor,
                )
                if not is_preflight_start_result(result) or result.frame_index is None:
                    continue
                sampling = sampling or self._sampling
                current[key] = sampling
                match = (key, sampling)
                if stable_match != match:
                    unique_frames.clear()
                    stable_match = match
                unique_frames.add(result.frame_index)
                matched = True
                reused = hints[key] is not None and sampling == hints[key]
                self._set_runtime_state(
                    calibration_state="checking" if reused else "calibrating",
                    calibration_reused=False, calibration_samples=len(unique_frames),
                )
                if len(unique_frames) < 3:
                    break
                self._sampling = sampling
                self._profile = profile
                self._awaiting_payload = True
                self._calibration_protocol = protocol
                self._calibration_capture_shape = raw_frame.shape[:2]
                saved = self._calibration_store.save(key, sampling)
                calibration_state = "reused" if reused else ("saved" if saved else "validated")
                self._publish("status", {
                    "state": "preflight_ok",
                    "message": self._preflight_detected_message(
                        selected_bpc=selected_bpc, detected_bpc=bpc, sampling=sampling,
                    ),
                    "frames_captured": frames_captured,
                    "preflight_required": True, "preflight_state": "ok",
                    "preflight_stage": "done", "requested_transfer_bpc": selected_bpc,
                    "transfer_bpc": bpc, "calibration_state": calibration_state,
                    "calibration_reused": reused, "calibration_samples": len(unique_frames),
                    "low_signal_streak": 0, "low_signal_duration_s": 0.0,
                    "low_signal_detected": False,
                })
                return True
            if not matched:
                stable_match = None
                unique_frames.clear()
                self._set_runtime_state(calibration_state="calibrating", calibration_samples=0)
            self._maybe_request_runtime_fallback(
                protocol_name="preflight", frames_captured=frames_captured,
                has_progress=False, low_signal_streak=low_signal_streak,
                low_signal_duration_s=low_signal_duration_s,
                no_progress_duration_s=max(0.0, now - wait_started_at),
            )
        self._publish("stopped", {"message": "Stopped by user", "frames_captured": frames_captured})
        return False

    def _run_fountain(self, cap: CaptureSource) -> None:
        protocol = get_protocol("fountain", profile=self._profile)
        session = ReceiveSession(mode="fountain", profile=self._profile, progress_interval_s=0.2)
        frames_captured = 0
        low_signal_streak = 0
        low_signal_since: float | None = None
        last_waiting_emit = 0.0
        started_at = time.time()
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
            low_signal_streak, low_signal_since, low_signal_duration_s = (
                self._update_low_signal_state(
                    frame,
                    low_signal_streak,
                    low_signal_since,
                    now,
                )
            )
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
            if self._is_calibration_tail(frame):
                continue
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
                    has_progress=session.has_progress,
                    low_signal_streak=low_signal_streak,
                    low_signal_duration_s=low_signal_duration_s,
                    no_progress_duration_s=max(0.0, now - started_at),
                )
                continue

            low_signal_streak = 0
            low_signal_since = None
            self._awaiting_payload = False
            events = session.feed_frame_result("fountain", result)
            for event in events:
                data = dict(event.data)
                data["frames_captured"] = frames_captured

                if event.kind == "status":
                    self._publish("status", data)
                    continue

                if event.kind == "progress":
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

    # -- sequential mode -------------------------------------------------

    def _run_sequential(self, cap: CaptureSource) -> None:
        protocol = get_protocol("sequential", profile=self._profile)
        session = ReceiveSession(mode="sequential", profile=self._profile)
        frames_captured = 0
        low_signal_streak = 0
        low_signal_since: float | None = None
        started_at = time.time()
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
            now = time.time()
            low_signal_streak, low_signal_since, low_signal_duration_s = (
                self._update_low_signal_state(
                    frame,
                    low_signal_streak,
                    low_signal_since,
                    now,
                )
            )
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
                    has_progress=session.has_progress,
                    low_signal_streak=low_signal_streak,
                    low_signal_duration_s=low_signal_duration_s,
                    no_progress_duration_s=max(0.0, now - started_at),
                )
                continue
            if is_preflight_start_result(result):
                continue

            low_signal_streak = 0
            low_signal_since = None
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

            self._maybe_publish_preview(frame)

            raw_frame = frame
            frame = self._ensure_size(raw_frame)
            if self._is_calibration_tail(frame):
                continue
            frames_probed += 1
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

            for bpc, profile, seq, fount in probe_candidates:
                detected = [None]

                def decode_sample(sampled):
                    sequential = seq.decode_frame(sampled)
                    if sequential.is_valid and not is_preflight_start_result(sequential):
                        detected[0] = "sequential"
                        return sequential
                    fountain = fount.decode_frame(sampled)
                    if fountain.is_valid:
                        detected[0] = "fountain"
                    return fountain

                result, geometry_cursor, sampling = self._decode_with_sampling_fallbacks(
                    frame, profile, decode_sample, geometry_candidates, geometry_cursor,
                )
                if result is None or not result.is_valid:
                    continue
                self._profile = profile
                protocol_name = detected[0]
                self._publish("status", {
                    "state": "detected",
                    "message": self._detected_message(
                        protocol_name=protocol_name.title(), selected_bpc=selected_bpc,
                        detected_bpc=bpc, sampling=self._sampling,
                    ),
                    "protocol": protocol_name,
                })
                # Detection must not consume the first payload/START packet.
                replay = _FirstFrameCapture(raw_frame, cap)
                if protocol_name == "sequential":
                    self._run_sequential(replay)
                else:
                    self._run_fountain(replay)
                return

            # Only failed payload probes count toward switching devices.
            # A long, valid calibration pattern is not a no-progress failure.
            self._maybe_request_runtime_fallback(
                protocol_name="auto",
                frames_captured=frames_probed,
                has_progress=False,
                low_signal_streak=black_streak,
            )

        self._publish("stopped", {
            "message": "Stopped by user",
            "frames_captured": frames_probed,
        })

    # -- helpers ---------------------------------------------------------

    def _is_calibration_tail(self, frame) -> bool:
        # Offline senders keep the pattern visible until the user confirms.
        # Do not search other geometries while this already-validated signal
        # is still on screen. Once payload starts this extra probe disappears.
        if not self._awaiting_payload or self._calibration_protocol is None:
            return False
        sampled = sample_grid(frame, self._profile, self._sampling)
        return is_preflight_start_result(self._calibration_protocol.decode_frame(sampled))

    def _ensure_size(self, frame):
        if (self._calibration_capture_shape is not None
                and frame.shape[:2] != self._calibration_capture_shape):
            # A new capture size changes the cache identity. CRC-based fallback
            # may recover the ongoing transfer, but its old hint is no longer
            # described as calibrated and is never saved under the new size.
            self._calibration_capture_shape = None
            self._sampling = (0, 0, 1.0, 1.0)
            self._set_runtime_state(calibration_state="calibrating", calibration_reused=False)
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
        keep_transfer_profile: bool = False,
    ) -> str:
        ox, oy, sx, sy = sampling
        geom_suffix = ""
        if sampling != (0, 0, 1.0, 1.0):
            geom_suffix = (
                f" | geometry offset=({ox},{oy}) scale=({sx:.4f},{sy:.4f})"
            )
        if keep_transfer_profile:
            return (
                "HDMI preflight detected on capture path "
                f"(safe bpc={detected_bpc}) — keeping transfer bpc={selected_bpc}"
                f"{geom_suffix}"
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

    def _update_low_signal_state(
        self,
        frame,
        streak: int,
        started_at: float | None,
        now: float,
    ) -> tuple[int, float | None, float]:
        streak = self._update_low_signal_streak(frame, streak)
        if streak <= 0:
            return 0, None, 0.0
        if started_at is None:
            started_at = now
        return streak, started_at, max(0.0, now - started_at)

    def _is_low_signal_detected(self, duration_s: float, streak: int) -> bool:
        return streak > 0 and duration_s >= _LOW_SIGNAL_DETECTED_AFTER_S

    def _maybe_request_runtime_fallback(
        self,
        *,
        protocol_name: str,
        frames_captured: int,
        has_progress: bool,
        low_signal_streak: int,
        low_signal_duration_s: float = 0.0,
        no_progress_duration_s: float = 0.0,
    ) -> None:
        if self._active_backend != cv2.CAP_DSHOW:
            return
        if not self._has_runtime_fallback_target():
            return
        if has_progress:
            return
        if low_signal_streak > 0 and low_signal_duration_s >= _RUNTIME_FALLBACK_LOW_SIGNAL_AFTER_S:
            self._request_capture_fallback(
                "Current DSHOW source is black or low-signal.",
            )
        if no_progress_duration_s >= _RUNTIME_FALLBACK_NO_PROGRESS_AFTER_S or frames_captured >= 360:
            self._request_capture_fallback(
                f"No decodable {protocol_name} frames found on current DSHOW source.",
            )

    def _has_runtime_fallback_target(self) -> bool:
        if not self._fallback_targets:
            return False
        if not self._restrict_runtime_fallback_to_dshow:
            return True
        return any(backend == cv2.CAP_DSHOW for _, backend in self._fallback_targets)

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

    def _describe_capture_target(self, device: int | str, backend: int | None) -> str:
        if isinstance(device, str) and device.startswith("ffmpeg-dshow:"):
            return f"{device.split(':', 1)[1]} via ffmpeg+dshow"
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
            "last_event_type": event_type,
        }
        if event_type == "status":
            updates.update(data)
            updates.setdefault(
                "preflight_state",
                self._runtime_state.get("preflight_state", "disabled"),
            )
        elif event_type == "progress":
            updates.update(data)
            updates.setdefault(
                "state",
                self._runtime_state.get("state", "receiving"),
            )
            updates.setdefault(
                "message",
                self._runtime_state.get("message", ""),
            )
        elif event_type == "complete":
            updates.update(data)
            updates.update({
                "state": "complete",
                "message": f"Complete: {data.get('filename', 'output')}",
                "protocol": data.get("protocol"),
            })
        elif event_type == "error":
            updates.update(data)
            updates.update({
                "state": "error",
                "message": data.get("message", "Error"),
            })
        elif event_type == "stopped":
            updates.update(data)
            updates.update({
                "state": "stopped",
                "message": data.get("message", "Stopped"),
            })
        self._set_runtime_state(**updates)
