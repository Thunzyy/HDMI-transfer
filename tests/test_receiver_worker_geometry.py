from __future__ import annotations

from dataclasses import replace

import numpy as np

from hdmi_transfer.core.config import PROFILES
from hdmi_transfer.core.protocols import get_protocol
from hdmi_transfer.web.receiver_worker import ReceiverWorker


def _worker(profile_name: str = "balanced") -> ReceiverWorker:
    profile = replace(PROFILES[profile_name], bits_per_channel=1)
    return ReceiverWorker(device=0, profile=profile, mode="auto")


def test_geometry_candidates_include_identity_and_browser_viewports():
    worker = _worker()
    profile = worker._profile
    cands = worker._build_geometry_candidates(profile)

    assert (0, 0, 1.0, 1.0) in cands

    expected = (
        8,  # centered 1904 in 1920
        (profile.height - 933) // 2,
        1904 / profile.width,
        933 / profile.height,
    )
    assert any(
        c[0] == expected[0]
        and c[1] == expected[1]
        and abs(c[2] - expected[2]) < 1e-6
        and abs(c[3] - expected[3]) < 1e-6
        for c in cands
    )


def test_estimate_sampling_from_frame_detects_active_box():
    worker = _worker()
    profile = worker._profile

    frame = np.zeros((profile.height, profile.width, 3), dtype=np.uint8)
    top, left = 73, 8
    vh, vw = 933, 1904
    rng = np.random.default_rng(1234)
    noise = rng.integers(0, 256, size=(vh, vw, 3), dtype=np.uint8)
    frame[top:top + vh, left:left + vw] = noise

    sampling = worker._estimate_sampling_from_frame(frame, profile)
    assert sampling is not None
    ox, oy, sx, sy = sampling

    assert abs(ox - left) <= 2
    assert abs(oy - top) <= 2
    assert abs(sx - (vw / profile.width)) < 0.02
    assert abs(sy - (vh / profile.height)) < 0.02


def _resize_nearest(frame: np.ndarray, height: int, width: int) -> np.ndarray:
    row_idx = np.linspace(0, frame.shape[0] - 1, height, dtype=int)
    col_idx = np.linspace(0, frame.shape[1] - 1, width, dtype=int)
    return frame[row_idx[:, None], col_idx[None, :]]


def test_manual_sequential_3bpc_probes_browser_geometry() -> None:
    profile = replace(PROFILES["balanced"], bits_per_channel=3)
    worker = ReceiverWorker(device=0, profile=profile, mode="sequential")
    protocol = get_protocol("sequential", profile=profile)
    payload = bytes(range(64))
    frame = protocol.encode_frame(payload, frame_index=0, total_frames=1)

    top, left = 73, 8
    vh, vw = 933, 1904
    captured = np.zeros_like(frame)
    captured[top:top + vh, left:left + vw] = _resize_nearest(frame, vh, vw)

    result = None
    sampling = None
    geometry_cursor = 0
    geometry_candidates = worker._build_geometry_candidates(profile)
    for _ in range(20):
        result, geometry_cursor, sampling = worker._decode_with_sampling_fallbacks(
            captured,
            profile,
            protocol.decode_frame,
            geometry_candidates,
            geometry_cursor,
        )
        if result is not None and result.is_valid:
            break

    assert result is not None
    assert result.is_valid
    assert result.data == payload
    assert sampling is not None
    ox, oy, sx, sy = sampling
    assert sampling != (0, 0, 1.0, 1.0)
    assert abs(ox - left) <= 2
    assert abs(oy - top) <= 2
    assert abs(sx - (vw / profile.width)) < 0.02
    assert abs(sy - (vh / profile.height)) < 0.02
