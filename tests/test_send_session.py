"""Tests for the shared send session extracted from the sender CLI."""

from __future__ import annotations

import math

from hdmi_exfil.core.config import PROFILES
from hdmi_exfil.core.file_handling.metadata import build_start_metadata


def test_send_session_emits_metadata_and_frame_stream(tmp_path):
    """Sequential sessions expose a START -> DATA -> END packet stream."""
    from hdmi_exfil.application.send_session import SendSession

    file_path = tmp_path / "payload.bin"
    file_data = (b"abc123" * 1000) + b"tail"
    file_path.write_bytes(file_data)

    session = SendSession.from_input(
        input_path=str(file_path),
        mode="sequential",
        profile_name="balanced",
    )

    packets = list(session.iter_frame_packets())
    data_packets = [packet for packet in packets if packet.kind == "data"]

    assert packets
    assert packets[0].kind == "start"
    assert packets[-1].kind == "end"
    assert len(data_packets) == math.ceil(
        len(file_data) / PROFILES["balanced"].seq_bytes_per_frame
    )
    assert session.filename == "payload.bin"
    assert session.file_data == file_data


def test_send_session_wraps_fountain_metadata_and_honors_limit(tmp_path):
    """Fountain sessions prepend metadata and stop at the configured limit."""
    from hdmi_exfil.application.send_session import SendSession

    file_path = tmp_path / "droplets.bin"
    file_data = b"fountain-data" * 2500
    file_path.write_bytes(file_data)

    session = SendSession.from_input(
        input_path=str(file_path),
        mode="fountain",
        profile_name="balanced",
        fountain_redundancy=1.5,
    )

    packets = list(session.iter_frame_packets())
    payload_size = PROFILES["balanced"].fount_bytes_per_frame
    expected_chunks = math.ceil(
        len(build_start_metadata("droplets.bin", file_data) + file_data) / payload_size
    )

    assert packets
    assert all(packet.kind == "droplet" for packet in packets)
    assert session.total_frames == expected_chunks
    assert session.max_droplets == math.ceil(expected_chunks * 1.5)
    assert len(packets) == session.max_droplets
    assert [packet.seed for packet in packets[:3]] == [1, 2, 3]
