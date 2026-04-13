from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from hdmi_exfil.core.config import FRAME_TYPE_DATA, FRAME_TYPE_START, PROFILES
from hdmi_exfil.core.protocols.base import FrameResult
from hdmi_exfil.web.receiver_worker import ReceiverWorker


class _FakeCap:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def read(self) -> tuple[bool, np.ndarray]:
        return True, self._frame.copy()


class _IdleCaptureSource:
    def __init__(self, source, width, height, fps, backend=None, **kwargs) -> None:
        self.actual_width = width
        self.actual_height = height
        self.actual_fps = float(fps)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def detach(self):
        return None


def test_reassemble_sequential_data_preserves_partial_last_chunk() -> None:
    profile = replace(PROFILES["balanced"], bits_per_channel=1)
    worker = ReceiverWorker(device=0, profile=profile, mode="sequential")
    bpf = profile.seq_bytes_per_frame

    full_data, missing = worker._reassemble_sequential_data({
        0: b"A" * bpf,
        1: b"tail",
    }, total_frames=2)

    assert missing == []
    assert full_data == (b"A" * bpf) + b"tail"


def test_sequential_finalizes_after_wrap_without_end_frame(
    tmp_path,
    monkeypatch,
) -> None:
    profile = replace(PROFILES["balanced"], bits_per_channel=1)
    worker = ReceiverWorker(device=0, profile=profile, mode="sequential")
    worker._output_dir = str(tmp_path)
    frame = np.zeros((profile.height, profile.width, 3), dtype=np.uint8)
    cap = _FakeCap(frame)
    events: list[dict] = []

    results = iter([
        FrameResult(
            data=b"A" * 8,
            frame_type=FRAME_TYPE_DATA,
            frame_index=0,
            total_frames=2,
            is_valid=True,
        ),
        FrameResult(
            data=b"B" * 4,
            frame_type=FRAME_TYPE_DATA,
            frame_index=1,
            total_frames=2,
            is_valid=True,
        ),
        FrameResult(
            data=b"A" * 8,
            frame_type=FRAME_TYPE_DATA,
            frame_index=0,
            total_frames=2,
            is_valid=True,
        ),
    ])

    worker._publish = lambda event_type, data: events.append({"type": event_type, "data": data})
    saved: dict[str, object] = {}

    def fake_write_output(file_content: bytes, filename: str, output_dir: str) -> str:
        saved.update({
            "file_content": file_content,
            "filename": filename,
            "output_dir": output_dir,
        })
        return str(tmp_path / filename)

    monkeypatch.setattr("hdmi_exfil.web.receiver_worker.write_output", fake_write_output)

    def fake_decode(frame, profile, decode_frame, geometry_candidates, geometry_cursor):
        try:
            return next(results), geometry_cursor, worker._sampling
        except StopIteration:
            worker._stop_event.set()
            return None, geometry_cursor, None

    worker._decode_with_sampling_fallbacks = fake_decode  # type: ignore[method-assign]

    worker._run_sequential(cap)

    complete = next(event for event in events if event["type"] == "complete")

    assert complete["data"]["total_chunks"] == 2
    assert complete["data"]["frames_captured"] == 3
    assert complete["data"]["bytes_received"] == 12
    assert complete["data"]["start_seen"] is False
    assert complete["data"]["end_seen"] is False
    assert complete["data"]["pass_count"] == 1
    assert complete["data"]["missing_frames"] == []
    assert complete["data"]["save_path"] == str(tmp_path / saved["filename"])
    assert saved["file_content"] == (b"A" * 8) + (b"B" * 4)
    assert saved["output_dir"] == str(tmp_path)


def test_worker_retries_alternate_capture_target_when_runtime_fallback_requested(
    monkeypatch,
) -> None:
    profile = replace(PROFILES["balanced"], bits_per_channel=1)
    worker = ReceiverWorker(
        device=1,
        profile=profile,
        mode="sequential",
        backend=int(cv2.CAP_DSHOW),
        fallback_targets=[(0, int(cv2.CAP_MSMF))],
    )

    open_attempts: list[tuple[int, int | None]] = []
    events: list[tuple[str, dict]] = []
    attempts = {"count": 0}

    class FakeCaptureSource(_IdleCaptureSource):
        def __init__(self, source, width, height, fps, backend=None, **kwargs) -> None:
            open_attempts.append((source, backend))
            super().__init__(source, width, height, fps, backend=backend, **kwargs)

    def fake_run_sequential(cap) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            worker._request_capture_fallback("retry")
        worker._publish("complete", {"filename": "ok.bin"})

    monkeypatch.setattr("hdmi_exfil.web.receiver_worker.CaptureSource", FakeCaptureSource)
    monkeypatch.setattr(worker, "_run_sequential", fake_run_sequential)
    original_publish = worker._publish

    def capture_publish(event_type, data):
        events.append((event_type, data))
        original_publish(event_type, data)

    worker._publish = capture_publish  # type: ignore[method-assign]

    worker.run()

    assert open_attempts == [
        (1, int(cv2.CAP_DSHOW)),
        (0, int(cv2.CAP_MSMF)),
    ]
    assert any(
        event_type == "status" and data.get("state") == "fallback"
        for event_type, data in events
    )
    assert events[-1] == ("complete", {"filename": "ok.bin"})


def test_worker_waits_for_preflight_before_receive_loop(monkeypatch) -> None:
    from hdmi_exfil.application.preflight import build_preflight_start_payload

    profile = replace(PROFILES["balanced"], bits_per_channel=1)
    worker = ReceiverWorker(
        device=0,
        profile=profile,
        mode="sequential",
        require_preflight=True,
    )
    cap = _FakeCap(np.zeros((profile.height, profile.width, 3), dtype=np.uint8))
    events: list[tuple[str, dict]] = []

    results = iter([
        FrameResult(
            data=b"\x00",
            frame_type=FRAME_TYPE_DATA,
            frame_index=0,
            total_frames=1,
            is_valid=False,
        ),
        FrameResult(
            data=build_preflight_start_payload(),
            frame_type=FRAME_TYPE_START,
            frame_index=0,
            total_frames=1,
            is_valid=True,
        ),
    ])

    original_publish = worker._publish

    def capture_publish(event_type, data):
        events.append((event_type, data))
        original_publish(event_type, data)

    worker._publish = capture_publish  # type: ignore[method-assign]

    def fake_decode(frame, profile, decode_frame, geometry_candidates, geometry_cursor):
        try:
            return next(results), geometry_cursor, worker._sampling
        except StopIteration:
            worker._stop_event.set()
            return None, geometry_cursor, None

    worker._decode_with_sampling_fallbacks = fake_decode  # type: ignore[method-assign]

    assert worker._wait_for_preflight(cap) is True
    assert worker.get_runtime_state()["preflight_state"] == "ok"
    assert any(
        event_type == "status" and data.get("state") == "preflight_ok"
        for event_type, data in events
    )
