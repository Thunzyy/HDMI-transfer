"""Large video profiles must respect the sequential wire header length."""

from dataclasses import replace

import pytest

from hdmi_transfer.core.config import PROFILES
from hdmi_transfer.core.protocols import get_protocol


@pytest.mark.parametrize("bpc", [2, 3])
def test_4k_sequential_capacity_roundtrip_respects_uint16_payload(bpc):
    profile = replace(PROFILES["quality"], bits_per_channel=bpc)
    assert profile.seq_bytes_per_frame == 65535
    protocol = get_protocol("sequential", profile=profile)
    payload = (bytes(range(256)) * 256)[:65535]
    frame = protocol.encode_frame(payload, frame_index=0, total_frames=1)
    decoded = protocol.decode_frame(frame[4::8, 4::8])
    assert decoded.is_valid is True
    assert decoded.data == payload

