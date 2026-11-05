"""Tests for the shared receive session."""

from __future__ import annotations

import math

import pytest

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


def _fountain_result(seed=1, *, total_chunks=100, payload=b"x" * 64):
    return FrameResult(
        data=payload,
        frame_type=None,
        frame_index=seed,
        total_frames=total_chunks,
        is_valid=True,
        max_frames=150,
    )


def test_fountain_duplicates_do_not_add_equations_but_are_counted():
    from hdmi_transfer.application.receive_session import ReceiveSession

    session = ReceiveSession(mode="fountain", profile_name="balanced")
    result = _fountain_result()
    for _ in range(20):
        events = session.feed_frame_result("fountain", result)

    decoder = session._fountain_decoder
    assert decoder is not None
    assert len(decoder.droplets) == 1
    assert len(decoder.chunks) == 0
    progress = next(event.data for event in events if event.kind == "progress")
    assert progress["droplets_received"] == 20
    assert progress["unique_droplets_received"] == 1
    assert progress["duplicate_droplets_received"] == 19
    assert progress["captured_bytes"] == 20 * 64
    assert progress["unique_bytes_received"] == 64
    assert progress["useful_bytes_decoded"] is None
    assert progress["eta_seconds"] == -1


def test_progress_throttle_skips_expensive_details_and_keeps_counts(monkeypatch):
    import hdmi_transfer.application.receive_session as receive_module

    clock = [10.0]
    monkeypatch.setattr(receive_module.time, "monotonic", lambda: clock[0])
    session = receive_module.ReceiveSession(
        mode="fountain", profile_name="balanced", progress_interval_s=0.2,
    )
    calls = []
    original = sorted

    def count_sort(values):
        calls.append(1)
        return original(values)

    monkeypatch.setattr(receive_module, "sorted", count_sort, raising=False)
    first = session.feed_frame_result("fountain", _fountain_result())
    assert any(event.kind == "progress" for event in first)
    for _ in range(30):
        assert session.feed_frame_result("fountain", _fountain_result()) == []
    assert len(calls) == 1

    clock[0] += 0.21
    later = session.feed_frame_result("fountain", _fountain_result())
    progress = next(event.data for event in later if event.kind == "progress")
    assert len(calls) == 2
    assert progress["droplets_received"] == 32
    assert progress["unique_droplets_received"] == 1


def test_fountain_useful_rate_excludes_metadata_padding_and_repeated_capture(monkeypatch):
    import hdmi_transfer.application.receive_session as receive_module
    from hdmi_transfer.core.prng import choose_indices

    clock = [10.0]
    monkeypatch.setattr(receive_module.time, "monotonic", lambda: clock[0])
    profile = PROFILES["balanced"]
    content = b"a" * 30000
    metadata = build_start_metadata("x.bin", content)
    wrapped = metadata + content
    size = profile.fount_bytes_per_frame
    total = math.ceil(len(wrapped) / size)
    first_seed = next(seed for seed in range(1, 10000) if choose_indices(seed, total) == {0})
    last_seed = next(seed for seed in range(1, 10000) if choose_indices(seed, total) == {total - 1})
    receiver = receive_module.ReceiveSession(mode="fountain", profile=profile)
    first = _fountain_result(first_seed, total_chunks=total, payload=wrapped[:size])
    receiver.feed_frame_result("fountain", first)

    clock[0] += 3.0
    repeated = receiver.feed_frame_result("fountain", first)
    progress = next(event.data for event in repeated if event.kind == "progress")
    useful_first = size - len(metadata)
    assert progress["useful_bytes_decoded"] == useful_first
    assert progress["unique_bytes_received"] == size
    assert progress["captured_bytes"] == size * 2
    assert progress["speed_kbps"] == round(useful_first / 3 / 1024, 1)
    assert progress["captured_speed_kbps"] > progress["speed_kbps"]
    assert progress["eta_seconds"] == -1

    last = wrapped[(total - 1) * size:].ljust(size, b"\x00")
    events = receiver.feed_frame_result(
        "fountain", _fountain_result(last_seed, total_chunks=total, payload=last),
    )
    progress = next(event.data for event in events if event.kind == "progress")
    assert progress["useful_bytes_decoded"] == useful_first + len(wrapped) - (total - 1) * size
    assert progress["useful_bytes_decoded"] < progress["unique_bytes_received"]


def test_throttled_fountain_roundtrip_completes_immediately_with_exact_useful_bytes(
    tmp_path, monkeypatch,
):
    import hdmi_transfer.application.receive_session as receive_module
    from hdmi_transfer.application.send_session import SendSession
    from hdmi_transfer.core.config import ResolutionProfile

    profile = ResolutionProfile("test", 128, 64, 8, 60)
    content = bytes(range(251)) * 3
    source = tmp_path / "small.bin"
    source.write_bytes(content)
    sender = SendSession.from_input(input_path=str(source), mode="fountain", profile=profile)
    receiver = receive_module.ReceiveSession(
        mode="fountain", profile=profile, progress_interval_s=1000,
    )
    monkeypatch.setattr(receive_module.time, "monotonic", lambda: 10.0)
    events = []
    for count, packet in enumerate(sender.iter_frame_packets()):
        events.extend(receiver.feed_sampled_grid(_sample_frame_centers(packet.frame, block_size=8)))
        # Repeated capture must not disturb a real roundtrip.
        events.extend(receiver.feed_sampled_grid(_sample_frame_centers(packet.frame, block_size=8)))
        if any(event.kind == "complete" for event in events):
            break
        assert count < 1000

    complete = next(event.data for event in events if event.kind == "complete")
    assert complete["file_content"] == content
    assert complete["sha256_ok"] is True
    assert complete["useful_bytes_decoded"] == len(content)
    assert complete["duplicate_droplets_received"] > 0
    assert len([event for event in events if event.kind == "progress"]) <= 2


def test_preflight_does_not_pin_auto_session_or_start_file_transfer():
    from hdmi_transfer.application.preflight import PREFLIGHT_FILENAME, PREFLIGHT_FILE_BYTES
    from hdmi_transfer.application.receive_session import ReceiveSession

    profile = PROFILES["balanced"]
    sequential = get_protocol("sequential", profile=profile)
    calibration = sequential.encode_start_frame(PREFLIGHT_FILENAME, PREFLIGHT_FILE_BYTES, 1)
    receiver = ReceiveSession(mode="auto", profile=profile)
    assert receiver.feed_sampled_grid(_sample_frame_centers(calibration, block_size=8)) == []
    assert receiver.detected_protocol is None
    assert receiver.has_progress is False

    fountain = get_protocol("fountain", profile=profile)
    content = b"actual file"
    payload = (build_start_metadata("actual.bin", content) + content).ljust(
        fountain.bytes_per_frame, b"\x00",
    )
    frame = fountain.encode_frame(payload, 0, 1, seed=1)
    events = receiver.feed_sampled_grid(_sample_frame_centers(frame, block_size=8))
    complete = next(event.data for event in events if event.kind == "complete")
    assert complete["filename"] == "actual.bin"
    assert complete["sha256_ok"] is True
    assert receiver.detected_protocol == "fountain"


@pytest.mark.parametrize("interval", [-1, float("nan"), float("inf")])
def test_progress_interval_rejects_invalid_values(interval):
    from hdmi_transfer.application.receive_session import ReceiveSession

    with pytest.raises(ValueError, match="progress_interval_s"):
        ReceiveSession(progress_interval_s=interval)
