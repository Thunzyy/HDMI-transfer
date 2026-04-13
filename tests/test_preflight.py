from __future__ import annotations

from hdmi_exfil.core.config import FRAME_TYPE_START
from hdmi_exfil.core.file_handling.metadata import build_start_metadata
from hdmi_exfil.core.protocols.base import FrameResult


def test_preflight_detects_expected_start_frame() -> None:
    from hdmi_exfil.application.preflight import (
        build_preflight_start_payload,
        is_preflight_start_result,
    )

    result = FrameResult(
        data=build_preflight_start_payload(),
        frame_type=FRAME_TYPE_START,
        frame_index=0,
        total_frames=1,
        is_valid=True,
    )

    assert is_preflight_start_result(result) is True


def test_preflight_rejects_regular_start_frame() -> None:
    from hdmi_exfil.application.preflight import is_preflight_start_result

    result = FrameResult(
        data=build_start_metadata("payload.bin", b"hello"),
        frame_type=FRAME_TYPE_START,
        frame_index=0,
        total_frames=1,
        is_valid=True,
    )

    assert is_preflight_start_result(result) is False
