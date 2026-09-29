"""Tests for the shared receive session."""

from __future__ import annotations

import math

from hdmi_transfer.core.config import FRAME_TYPE_DATA, PROFILES
from hdmi_transfer.core.file_handling.metadata import build_start_metadata
from hdmi_transfer.core.protocols import get_protocol
from hdmi_transfer.core.protocols.base import FrameResult


def _sample_frame_centers(frame, *, block_size: int):
    half = block_size // 2
    return frame[half::block_size, half::block_size, :]


def test_receive_session_emits_progress_and_complete_for_sequential_transfer():
    from hdmi_transfer.application.receive_session import ReceiveSession

    profile = PROFILES["balanced"]
    protocol = get_protocol("sequential", profile=profile)
    file_data = (b"abc123" * 1000) + b"tail"
    total_frames = math.ceil(len(file_data) / profile.seq_bytes_per_frame)
    session = ReceiveSession(mode="sequential", profile_name="balanced")
    events = []

    start_frame = protocol.encode_start_frame("payload.bin", file_data, total_frames)
    events.extend(
        session.feed_sampled_grid(
            _sample_frame_centers(start_frame, block_size=profile.block_size),
        ),
    )

    for frame_index in range(total_frames):
        start = frame_index * profile.seq_bytes_per_frame
        end = min(start + profile.seq_bytes_per_frame, len(file_data))
        frame = protocol.encode_frame(
            file_data[start:end],
            frame_index=frame_index,
            total_frames=total_frames,
        )
        events.extend(
            session.feed_sampled_grid(
                _sample_frame_centers(frame, block_size=profile.block_size),
            ),
        )

    end_frame = protocol.encode_end_frame(total_frames)
    events.extend(
        session.feed_sampled_grid(
            _sample_frame_centers(end_frame, block_size=profile.block_size),
        ),
    )

    progress = [event for event in events if event.kind == "progress"]
    complete = next(event for event in events if event.kind == "complete")

    assert progress
    assert complete.data["protocol"] == "sequential"
    assert complete.data["filename"] == "payload.bin"
    assert complete.data["file_content"] == file_data
    assert complete.data["start_seen"] is True
    assert complete.data["end_seen"] is True


def test_receive_session_finalizes_after_wrap_without_end_frame():
    from hdmi_transfer.application.receive_session import ReceiveSession

    session = ReceiveSession(mode="sequential", profile_name="balanced")
    events = []

    for result in [
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
    ]:
        events.extend(session.feed_frame_result("sequential", result))

    complete = next(event for event in events if event.kind == "complete")

    assert complete.data["protocol"] == "sequential"
    assert complete.data["file_content"] == (b"A" * 8) + (b"B" * 4)
    assert complete.data["pass_count"] == 1
    assert complete.data["start_seen"] is False
    assert complete.data["end_seen"] is False
    assert complete.data["missing_frames"] == []


def test_receive_session_completes_single_chunk_fountain_transfer():
    from hdmi_transfer.application.receive_session import ReceiveSession

    profile = PROFILES["balanced"]
    protocol = get_protocol("fountain", profile=profile)
    file_data = b"fountain-data" * 32
    wrapped = build_start_metadata("droplets.bin", file_data) + file_data
    payload = wrapped.ljust(protocol.bytes_per_frame, b"\x00")
    session = ReceiveSession(mode="fountain", profile_name="balanced")

    frame = protocol.encode_frame(
        payload,
        frame_index=0,
        total_frames=1,
        seed=1,
        expected_droplets=1,
    )
    events = session.feed_sampled_grid(
        _sample_frame_centers(frame, block_size=profile.block_size),
    )
    complete = next(event for event in events if event.kind == "complete")

    assert complete.data["protocol"] == "fountain"
    assert complete.data["filename"] == "droplets.bin"
    assert complete.data["file_content"] == file_data
    assert complete.data["total_chunks"] == 1
