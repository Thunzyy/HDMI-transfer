from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

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


@pytest.mark.parametrize("bpc", [1, 2, 3])
def test_complete_calibration_pattern_roundtrips_at_4k(bpc):
    from hdmi_transfer.application.preflight import build_calibration_frame, is_calibration_frame_valid
    from hdmi_transfer.core.config import PROFILES
    from hdmi_transfer.core.protocols import get_protocol

    profile = replace(PROFILES["quality"], bits_per_channel=bpc)
    frame = build_calibration_frame(profile, 17)
    sampled = frame[4::8, 4::8]
    result = get_protocol("sequential", profile=profile).decode_frame(sampled)
    assert result.is_valid
    assert result.frame_index == 17
    assert is_calibration_frame_valid(sampled, profile, result)


@pytest.mark.parametrize("bpc", [2, 3])
def test_corrupted_lower_4k_pattern_is_rejected_even_when_payload_crc_is_valid(bpc):
    from hdmi_transfer.application.preflight import build_calibration_frame, is_calibration_frame_valid
    from hdmi_transfer.core.config import PROFILES
    from hdmi_transfer.core.protocols import get_protocol

    profile = replace(PROFILES["quality"], bits_per_channel=bpc)
    frame = build_calibration_frame(profile, 19)
    # Alter the last complete block, far beyond the uint16 CRC-covered payload.
    frame[-8:, -8:] = 255 - frame[-8:, -8:]
    sampled = frame[4::8, 4::8]
    result = get_protocol("sequential", profile=profile).decode_frame(sampled)
    assert result.is_valid, "The regression requires a valid prefix/CRC"
    assert not is_calibration_frame_valid(sampled, profile, result)


def test_metadata_only_legacy_preflight_cannot_qualify_full_pattern_calibration():
    from hdmi_transfer.application.preflight import (
        build_preflight_start_payload, is_preflight_start_result, is_calibration_frame_valid,
    )
    from hdmi_transfer.core.config import PROFILES
    from hdmi_transfer.core.protocols import get_protocol

    profile = PROFILES["balanced"]
    protocol = get_protocol("sequential", profile=profile)
    frame = protocol.encode_frame(build_preflight_start_payload(), 0, 1, frame_type=FRAME_TYPE_START)
    sampled = frame[4::8, 4::8]
    result = protocol.decode_frame(sampled)
    assert is_preflight_start_result(result)
    assert not is_calibration_frame_valid(sampled, profile, result)


@pytest.mark.parametrize("bpc", [2, 3])
def test_python_and_actual_browser_calibration_builders_match_at_4k(bpc):
    from hdmi_transfer.application.preflight import build_calibration_frame, build_preflight_start_payload
    from hdmi_transfer.core.config import PROFILES
    from hdmi_transfer.core.protocols.encoding import pixels_to_bytes
    from hdmi_transfer.interfaces.browser_sender import render_protocol_javascript

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed for the browser/Python protocol comparison")
    source = (Path(__file__).resolve().parents[1] / "src/interfaces/browser_sender/app.js").read_text(encoding="utf-8")

    def function(name):
        match = re.search(r"  function " + name + r"\(.*?\n  }\n", source, re.S)
        assert match is not None
        return match.group(0)

    crc_table = source[source.index("  const CRC32_TABLE"):source.index("  function crc32")]
    script = render_protocol_javascript() + crc_table
    script += "\n".join(function(name) for name in (
        "crc32", "bytesPerFrameForBpc", "applyPreflightVisualFiller", "buildSeqFrame", "renderPreflightFrame",
    ))
    script += "\nconst config = {rows: 270, cols: 480};\n"
    script += "const state = " + json.dumps({
        "preflightPayload": list(build_preflight_start_payload()), "preflightPayloads": {},
        "preflightRenderBpc": bpc, "preflightFrames": 29,
    }) + ";\n"
    script += "state.preflightPayload = new Uint8Array(state.preflightPayload);\n"
    script += "function bytesToValues(bytes) { state.captured = Buffer.from(bytes); }\n"
    script += "function drawValues() {}\nrenderPreflightFrame();\n"
    script += "process.stdout.write(require('crypto').createHash('sha256').update(state.captured).digest('hex'));\n"
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    profile = replace(PROFILES["quality"], bits_per_channel=bpc)
    sampled = build_calibration_frame(profile, 29)[4::8, 4::8]
    python_bytes = pixels_to_bytes(sampled[..., ::-1], bpc)
    assert result.stdout == hashlib.sha256(python_bytes).hexdigest()
