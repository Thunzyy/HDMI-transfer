from __future__ import annotations

from pathlib import Path


def test_receiver_html_defaults_to_fountain_bpc2_balanced() -> None:
    receiver_html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "web"
        / "static"
        / "receiver.html"
    )
    text = receiver_html.read_text(encoding="utf-8")

    assert (
        '<option value="balanced" selected>'
        'Balanced - recommended for most 2-PC setups'
        '</option>'
    ) in text
    assert '<option value="fountain" selected>Fountain - recommended default</option>' in text
    assert '<option value="2" selected>2 bpc - recommended default</option>' in text
    assert 'Recommended for most 2-PC setups: Fountain + Balanced + 2 bpc' in text
    assert '<span class="help-tip" tabindex="0">?' in text


def test_settings_html_exposes_default_bpc_and_fountain_defaults() -> None:
    settings_html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "web"
        / "static"
        / "settings.html"
    )
    text = settings_html.read_text(encoding="utf-8")

    assert (
        '<option value="balanced" selected>'
        'Balanced - recommended for most 2-PC setups'
        '</option>'
    ) in text
    assert '<option value="fountain" selected>Fountain - recommended default</option>' in text
    assert 'id="defaultBpc"' in text
    assert '<option value="2" selected>2 bpc - recommended default</option>' in text
    assert "const defaultBpc = document.getElementById(\"defaultBpc\");" in text
    assert "defaultBpc: Number(defaultBpc.value)," in text
    assert 'Shared defaults used by Send and Receive' in text
    assert '<span class="help-tip" tabindex="0">?' in text
