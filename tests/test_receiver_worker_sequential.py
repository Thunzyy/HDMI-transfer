from __future__ import annotations

from dataclasses import replace

import numpy as np

from hdmi_exfil.core.config import FRAME_TYPE_DATA, PROFILES
from hdmi_exfil.core.protocols.base import FrameResult
from hdmi_exfil.web.receiver_worker import ReceiverWorker


class _FakeCap:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def read(self) -> tuple[bool, np.ndarray]:
        return True, self._frame.copy()


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
