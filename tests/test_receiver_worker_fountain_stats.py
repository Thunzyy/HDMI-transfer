from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

from hdmi_exfil.core.config import PROFILES
from hdmi_exfil.web.receiver_worker import ReceiverWorker


def test_publish_fountain_progress_includes_unique_droplet_count():
    profile = replace(PROFILES["balanced"], bits_per_channel=1)
    worker = ReceiverWorker(device=0, profile=profile, mode="fountain")
    events: list[tuple[str, dict]] = []
    worker._publish = lambda event_type, data: events.append((event_type, data))

    decoder = SimpleNamespace(
        chunks={0: b"a", 1: b"b"},
        droplets=[
            [set([2, 3]), b"x"],
            [set([4]), b"y"],
        ],
    )

    worker._publish_fountain_progress(
        decoder,
        K=10,
        payload=b"x" * 16,
        bytes_received=256,
        droplets_received=12,
        unique_droplets_received=9,
        expected_droplets=15,
        frames_captured=20,
        start_time=time.time() - 3.0,
        emit_indices=False,
    )

    assert len(events) == 1
    event_type, data = events[0]
    assert event_type == "progress"
    assert data["droplets_received"] == 12
    assert data["unique_droplets_received"] == 9
    assert data["expected_droplets"] == 15
