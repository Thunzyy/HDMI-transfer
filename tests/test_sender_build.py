from __future__ import annotations

from hdmi_exfil.domain.protocol_manifest import get_protocol_manifest
from tools.build_sender_html import build_sender_html


def test_build_sender_html_uses_protocol_manifest(tmp_path):
    output = build_sender_html(tmp_path / "sender.html")
    text = output.read_text(encoding="utf-8")
    manifest = get_protocol_manifest()

    assert "const SEQ_MAGIC = 0xDA7A;" in text
    assert f"const FOUNTAIN_MAGIC = 0x{manifest.fountain.current_magic:04X};" in text
    assert f"const FOUNTAIN_HEADER_PRE_CRC = {manifest.fountain.header_pre_crc};" in text


def test_build_sender_html_is_reproducible(tmp_path):
    first = build_sender_html(tmp_path / "sender-a.html").read_bytes()
    second = build_sender_html(tmp_path / "sender-b.html").read_bytes()

    assert first == second
