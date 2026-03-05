from __future__ import annotations

from dataclasses import replace

import numpy as np

from hdmi_exfil.core.config import PROFILES
from hdmi_exfil.web.receiver_worker import ReceiverWorker


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
