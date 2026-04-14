from __future__ import annotations

from pathlib import Path


def test_receiver_html_defaults_to_fountain_bpc2_balanced() -> None:
    receiver_html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "hdmi_exfil"
        / "web"
        / "static"
        / "receiver.html"
    )
    text = receiver_html.read_text(encoding="utf-8")

    assert '<option value="balanced" selected>balanced (1080p@60)</option>' in text
    assert '<option value="fountain" selected>fountain</option>' in text
    assert '<option value="2" selected>2 bpc — Fast (2x)</option>' in text


def test_settings_html_exposes_default_bpc_and_fountain_defaults() -> None:
    settings_html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "hdmi_exfil"
        / "web"
        / "static"
        / "settings.html"
    )
    text = settings_html.read_text(encoding="utf-8")

    assert '<option value="balanced" selected>Balanced (1080p @60fps)</option>' in text
    assert '<option value="fountain" selected>Fountain</option>' in text
    assert 'id="defaultBpc"' in text
    assert '<option value="2" selected>2 bpc - Fast</option>' in text
    assert "const defaultBpc = document.getElementById(\"defaultBpc\");" in text
    assert "defaultBpc: Number(defaultBpc.value)," in text
