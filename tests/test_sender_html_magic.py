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
    assert 'protocol: "fountain", bpc: 2,' in text
    assert "fountainAutoStop: true," in text
    assert 'sequentialRedundancy: 1,' in text
    assert 'fpsMode: "profile"' in text
    assert 'const APP_SETTINGS_KEY = "hdmi_exfil_settings";' in text
    assert "applySharedAppDefaults()" in text
    assert "Recommended for most 2-PC setups: Fountain + Balanced + 2 bpc." in text
    assert "Speed is capped here; use a dedicated 120Hz+ HDMI path for gains." in text


def test_sender_html_contains_preflight_handshake_logic() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")

    assert "PREFLIGHT_FILENAME" in text
    assert 'resolveReceiverApiUrl("/api/receive/status")' in text
    assert "preflight_state" in text
    assert "preflight_stage" in text
    assert "transfer_bpc" in text
    assert "PREFLIGHT_TRANSFER_CANDIDATE_TIMEOUT_MS" in text


def test_sender_html_waits_for_receiver_before_fountain_autostop() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")

    assert "waitForReceiverCompletion" in text
    assert 'state.phase = "wait_complete"' in text
    assert "Receiver still active after local fountain target" in text


def test_sender_html_supports_explicit_receiver_api_base_url() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")

    assert 'apiBaseUrl: ""' in text
    assert 'const apiBaseUrl = params.get("apiBaseUrl")' in text
    assert "resolveReceiverApiUrl(" in text


def test_sender_html_contains_dense_preflight_filler() -> None:
    sender_html = Path(__file__).resolve().parents[1] / "sender.html"
    text = sender_html.read_text(encoding="utf-8")

    assert "PREFLIGHT_BITS_PER_CHANNEL = 1" in text
    assert "PREFLIGHT_FILLER_BYTES" in text
    assert "applyPreflightVisualFiller" in text
    assert "applyNegotiatedTransferBpc" in text
