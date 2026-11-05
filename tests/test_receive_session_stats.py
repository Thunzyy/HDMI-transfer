"""Progress guarantees belong to the active shared receive service."""

from hdmi_transfer.application.receive_session import ReceiveSession
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
