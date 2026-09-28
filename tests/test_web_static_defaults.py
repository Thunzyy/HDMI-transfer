from __future__ import annotations

from pathlib import Path
from html.parser import HTMLParser


class SelectedOptions(HTMLParser):
    """Read actual form defaults independently of presentation wording."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.current_select = None
        self.selected = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.current_select = attrs.get("id")
        elif tag == "option" and "selected" in attrs:
            self.selected[self.current_select] = attrs.get("value")

    def handle_endtag(self, tag):
        if tag == "select":
            self.current_select = None


def test_receiver_html_defaults_to_fountain_bpc2_balanced() -> None:
    receiver_html = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "web"
        / "static"
        / "receiver.html"
    )
    text = receiver_html.read_text(encoding="utf-8")

    defaults = SelectedOptions(text).selected
    assert defaults["profileSelect"] == "balanced"
    assert defaults["modeSelect"] == "fountain"
    assert defaults["bpcSelect"] == "2"
    assert defaults["previewQualitySelect"] == "45"
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

    defaults = SelectedOptions(text).selected
    assert defaults["defaultProfile"] == "balanced"
    assert defaults["defaultMode"] == "fountain"
    assert defaults["defaultBpc"] == "2"
    assert "const defaultBpc = document.getElementById(\"defaultBpc\");" in text
    assert "defaultBpc: Number(defaultBpc.value)," in text
    assert 'Shared defaults used by Send and Receive' in text
    assert '<span class="help-tip" tabindex="0">?' in text
