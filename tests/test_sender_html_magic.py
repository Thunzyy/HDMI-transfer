from __future__ import annotations

from pathlib import Path

from hdmi_exfil.core.config import SEQ_MAGIC
from hdmi_exfil.domain.protocol_manifest import get_protocol_manifest
from tools.build_sender_html import render_sender_html


def test_sender_html_sequential_magic_matches_core_config() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")
    manifest = get_protocol_manifest()
    expected = f"const SEQ_MAGIC = 0x{SEQ_MAGIC:04X};"
    assert expected in text
    assert f"const FOUNTAIN_MAGIC = 0x{manifest.fountain.current_magic:04X};" in text


def test_sender_html_matches_generated_output() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    assert sender_html.read_text(encoding="utf-8") == render_sender_html()


def test_sender_html_defaults_match_python_sender_behavior() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")
    assert 'sequentialRedundancy: 1,' in text
    assert 'fpsMode: "profile"' in text


def test_sender_html_contains_preflight_handshake_logic() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")

    assert "PREFLIGHT_FILENAME" in text
    assert 'fetch("/api/receive/status"' in text
    assert "preflight_state" in text
