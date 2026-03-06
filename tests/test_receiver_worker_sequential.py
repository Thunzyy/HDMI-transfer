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


def test_sequential_finalizes_after_wrap_without_end_frame() -> None:
    profile = replace(PROFILES["balanced"], bits_per_channel=1)
    worker = ReceiverWorker(device=0, profile=profile, mode="sequential")
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

    def fake_decode(frame, profile, decode_frame, geometry_candidates, geometry_cursor):
        try:
            return next(results), geometry_cursor, worker._sampling
        except StopIteration:
            worker._stop_event.set()
            return None, geometry_cursor, None

    finalized: dict[str, object] = {}

    def fake_finalize(
        received,
        total_frames,
        expected_size,
        expected_sha256,
        expected_name,
        start_time,
        frames_captured,
        bytes_received,
        *,
        saw_start,
        saw_end,
        pass_count,
    ) -> None:
        finalized.update({
            "received": dict(received),
            "total_frames": total_frames,
            "frames_captured": frames_captured,
            "bytes_received": bytes_received,
            "saw_start": saw_start,
            "saw_end": saw_end,
            "pass_count": pass_count,
        })

    worker._decode_with_sampling_fallbacks = fake_decode  # type: ignore[method-assign]
    worker._finalize_sequential = fake_finalize  # type: ignore[method-assign]

    worker._run_sequential(cap)

    assert finalized["total_frames"] == 2
    assert finalized["frames_captured"] == 3
    assert finalized["bytes_received"] == 12
    assert finalized["saw_start"] is False
    assert finalized["saw_end"] is False
    assert finalized["pass_count"] == 1
    assert finalized["received"] == {0: b"A" * 8, 1: b"B" * 4}
