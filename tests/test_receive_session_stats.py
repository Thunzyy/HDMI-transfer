"""Progress guarantees belong to the active shared receive service."""

import pytest

import hdmi_transfer.application.receive_session as receive_module
from hdmi_transfer.adapters.receive_worker import ReceiverWorker
from hdmi_transfer.application.receive_session import ReceiveSession
from hdmi_transfer.core.config import PROFILES
from hdmi_transfer.core.file_handling.metadata import build_start_metadata
from hdmi_transfer.core.prng import choose_indices
from hdmi_transfer.core.protocols import get_protocol
from hdmi_transfer.core.protocols.base import FrameResult


def test_fountain_progress_includes_unique_and_expected_droplet_counts():
    receiver = ReceiveSession(mode="fountain", profile_name="balanced")
    for seed in [*range(1, 10), 1, 2, 3]:
        events = receiver.feed_frame_result("fountain", FrameResult(
            data=b"x" * 64,
            frame_type=None,
            frame_index=seed,
            total_frames=100,
            is_valid=True,
            max_frames=150,
        ))

    progress = next(event.data for event in events if event.kind == "progress")
    assert progress["droplets_received"] == 12
    assert progress["unique_droplets_received"] == 9
    assert progress["expected_droplets"] == 150
    assert progress["duplicate_droplets_received"] == 3
    assert progress["bytes_received"] == 12 * 64
    assert progress["unique_bytes_received"] == 9 * 64


@pytest.mark.parametrize("duration", [0.0, 0.5, 1.9, 3.0])
def test_fountain_completion_replaces_progress_rates_in_runtime_state(monkeypatch, duration):
    profile = PROFILES["balanced"]
    protocol = get_protocol("fountain", profile=profile)
    payload_size = protocol.bytes_per_frame
    content = b"x" * (payload_size + 20)
    wrapped = build_start_metadata("quick.bin", content) + content
    assert payload_size < len(wrapped) < 2 * payload_size
    grids = []
    for index in range(2):
        seed = next(seed for seed in range(1, 10000) if choose_indices(seed, 2) == {index})
        payload = wrapped[index * payload_size:(index + 1) * payload_size].ljust(
            payload_size, b"\x00",
        )
        frame = protocol.encode_frame(payload, index, 2, seed=seed)
        half = profile.block_size // 2
        grids.append(frame[half::profile.block_size, half::profile.block_size, :])

    clock = [10.0]
    monkeypatch.setattr(receive_module.time, "monotonic", lambda: clock[0])
    receiver = ReceiveSession(mode="fountain", profile=profile)
    events = receiver.feed_sampled_grid(grids[0])
    events.extend(receiver.feed_sampled_grid(grids[0]))
    clock[0] += duration
    events.extend(receiver.feed_sampled_grid(grids[1]))
    complete = next(event.data for event in events if event.kind == "complete")

    assert complete["file_content"] == content
    assert complete["sha256_ok"] is True
    expected_rates = {
        "speed_kbps": round(len(content) / duration / 1024, 1) if duration else 0,
        "captured_speed_kbps": round(3 * payload_size / duration / 1024, 1) if duration else 0,
        "unique_speed_kbps": round(2 * payload_size / duration / 1024, 1) if duration else 0,
    }
    assert {key: complete[key] for key in expected_rates} == expected_rates
    assert complete["speed_mbps"] == (
        round(len(content) * 8 / duration / 1_000_000, 2) if duration else 0
    )
    assert complete["percent"] == 100
    assert complete["eta_seconds"] == 0

    # The polling API merges successive events; terminal values must replace
    # the provisional rate, 99.9% and unknown ETA from the last progress event.
    worker = ReceiverWorker(device=0, profile=profile)
    for event in events:
        worker._publish(event.kind, {
            key: value for key, value in event.data.items() if key != "file_content"
        })
    state = worker.get_runtime_state()
    assert state["state"] == "complete"
    assert {key: state[key] for key in expected_rates} == expected_rates
    assert state["percent"] == 100
    assert state["eta_seconds"] == 0
