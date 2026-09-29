from __future__ import annotations

from hdmi_transfer.core.config import FRAME_TYPE_START
from hdmi_transfer.core.file_handling.metadata import build_start_metadata
from hdmi_transfer.core.protocols.base import FrameResult


def test_preflight_detects_expected_start_frame() -> None:
    from hdmi_transfer.application.preflight import (
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
    from hdmi_transfer.application.preflight import is_preflight_start_result

    result = FrameResult(
        data=build_start_metadata("payload.bin", b"hello"),
        frame_type=FRAME_TYPE_START,
        frame_index=0,
        total_frames=1,
        is_valid=True,
    )

    assert is_preflight_start_result(result) is False


def test_preflight_filler_preserves_prefix_and_densifies_tail() -> None:
    from hdmi_transfer.application.preflight import (
        PREFLIGHT_BITS_PER_CHANNEL,
        apply_preflight_visual_filler,
    )

    assert PREFLIGHT_BITS_PER_CHANNEL == 1

    frame = bytearray(256)
    prefix = bytes(range(32))
    frame[: len(prefix)] = prefix

    apply_preflight_visual_filler(frame, used_prefix_len=len(prefix))

    assert bytes(frame[: len(prefix)]) == prefix
    assert any(byte != 0 for byte in frame[len(prefix):])
    assert sum(1 for byte in frame[len(prefix):] if byte != 0) > 128
