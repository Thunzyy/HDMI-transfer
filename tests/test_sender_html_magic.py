from __future__ import annotations

from pathlib import Path

from hdmi_exfil.core.config import SEQ_MAGIC


def test_sender_html_sequential_magic_matches_core_config() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")
    expected = f"const SEQ_MAGIC = 0x{SEQ_MAGIC:04X};"
    assert expected in text


def test_sender_html_defaults_match_python_sender_behavior() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")
    assert 'sequentialRedundancy: 1,' in text
    assert 'fpsMode: "profile"' in text
