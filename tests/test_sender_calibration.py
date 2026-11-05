"""Sender calibration uses real protocol frames with an isolated display/store."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from hdmi_transfer.application.preflight import is_preflight_start_result
from hdmi_transfer.core import settings
from hdmi_transfer.core.config import ResolutionProfile
from hdmi_transfer.core.protocols import get_protocol
from hdmi_transfer.interfaces.cli import send


PROFILE = ResolutionProfile("test", 256, 128, 8, 60, bits_per_channel=2)
MONITOR = {"left": 256, "top": 0, "width": 256, "height": 128}


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "_SETTINGS_DIR", tmp_path / "settings")
    monkeypatch.setattr(settings, "_SETTINGS_FILE", tmp_path / "settings" / "settings.json")


class FakeRenderer:
    def __init__(self, keys=(), *, clock=None, display=(256, 128)):
        self.keys = list(keys)
        self.frames = []
        self.clock = clock
        self._screen = SimpleNamespace(get_size=lambda: display)

    def show(self, frame, delay_ms=1):
        self.frames.append(frame.copy())
        if len(self.frames) > 30:
            raise AssertionError("Calibration did not finish or cancel")
        if self.clock is not None:
            self.clock[0] += 0.4
        return self.keys.pop(0) if self.keys else 255

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def calibrate(renderer, **changes):
    options = dict(
        profile=PROFILE, mode="fountain", renderer_type="pygame", screen=1,
        monitor=MONITOR, fps=60, delay=16,
    )
    options.update(changes)
    return send._calibrate_sender(renderer, **options)


def test_first_calibration_requires_enter_and_emits_distinct_valid_frames():
    settings.set_value("receiver", "device_name", "preserved receiver")
    renderer = FakeRenderer([13, 255, 13])
    assert calibrate(renderer) is True
    assert len(renderer.frames) == 3
    protocol = get_protocol("sequential", profile=PROFILE)
    decoded = [protocol.decode_frame(frame[4::8, 4::8]) for frame in renderer.frames]
    assert all(is_preflight_start_result(result) for result in decoded)
    assert [result.frame_index for result in decoded] == [0, 1, 2]
    assert all(len(result.data) == PROFILE.seq_bytes_per_frame for result in decoded)
    saved = settings.get("sender", "calibration_confirmation")
    assert saved["bpc"] == 2
    assert saved["monitor"] == MONITOR
    assert saved["display"] == [256, 128]
    assert settings.get("receiver", "device_name") == "preserved receiver"


def test_repeat_calibration_rechecks_without_human_prompt(monkeypatch):
    assert calibrate(FakeRenderer([255, 255, 13])) is True
    clock = [10.0]
    monkeypatch.setattr(send.time, "monotonic", lambda: clock[0])
    renderer = FakeRenderer(clock=clock)
    assert calibrate(renderer) is True
    assert len(renderer.frames) >= 3
    assert clock[0] >= 11.0


@pytest.mark.parametrize("change", ["force", "bpc", "screen", "display", "fps"])
def test_changed_configuration_or_forced_calibration_needs_confirmation(change, monkeypatch):
    assert calibrate(FakeRenderer([255, 255, 13])) is True
    original = settings.get("sender", "calibration_confirmation")
    options = {}
    display = (256, 128)
    if change == "force":
        options["force"] = True
    elif change == "bpc":
        options["profile"] = replace(PROFILE, bits_per_channel=1)
    elif change == "screen":
        options["screen"] = 0
    elif change == "display":
        display = (250, 128)
    elif change == "fps":
        options["fps"] = 30
    clock = [10.0]
    monkeypatch.setattr(send.time, "monotonic", lambda: clock[0])
    renderer = FakeRenderer([255, 255, 255, 27], display=display, clock=clock)
    assert calibrate(renderer, **options) is False
    assert settings.get("sender", "calibration_confirmation") == original


def test_malformed_saved_confirmation_is_ignored(monkeypatch):
    settings.set_value("sender", "calibration_confirmation", "invalid")
    clock = [10.0]
    monkeypatch.setattr(send.time, "monotonic", lambda: clock[0])
    assert calibrate(FakeRenderer([255, 255, 255, ord("q")], clock=clock)) is False


def test_first_calibration_waits_for_human_even_after_long_pattern(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(send.time, "monotonic", lambda: clock[0])
    renderer = FakeRenderer([*[255] * 15, 27], clock=clock)
    assert calibrate(renderer) is False
    assert clock[0] > 16.0
    assert settings.get("sender", "calibration_confirmation") is None


def test_run_send_does_not_emit_file_data_when_calibration_cancelled(monkeypatch, tmp_path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    renderer = FakeRenderer([27])
    monkeypatch.setattr(send, "PygameRenderer", lambda **kwargs: renderer)
    monkeypatch.setattr(send, "get_monitors", lambda: [MONITOR])
    monkeypatch.setattr(send, "warmup_numba", lambda: None)
    sent = []
    monkeypatch.setattr(send, "_send_fountain", lambda *args, **kwargs: sent.append(args))
    send.run_send(str(source), profile=PROFILE)
    assert sent == []
    assert settings.get("sender", "calibration_confirmation") is None


def test_run_send_defaults_and_explicit_legacy_profile(monkeypatch, tmp_path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    renderer = FakeRenderer()
    monkeypatch.setattr(send, "PygameRenderer", lambda **kwargs: renderer)
    monkeypatch.setattr(send, "get_monitors", lambda: [MONITOR])
    monkeypatch.setattr(send, "warmup_numba", lambda: None)
    sent = []
    monkeypatch.setattr(send, "_send_fountain", lambda session, *args, **kwargs: sent.append(session))
    send.run_send(str(source), calibration=False)
    send.run_send(str(source), profile=replace(PROFILE, bits_per_channel=1), calibration=False)
    assert sent[0].mode == "fountain"
    assert sent[0].profile.name == "balanced"
    assert sent[0].profile.bits_per_channel == 2
    assert sent[1].profile.bits_per_channel == 1
    assert renderer.frames == []


def test_cli_encoding_override_and_calibration_flags(monkeypatch):
    captured = {}
    monkeypatch.setattr(send, "run_send", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr("sys.argv", ["hdmi-send", "file.bin", "--bpc", "3", "--recalibrate"])
    send.main()
    assert captured["mode"] == "fountain"
    assert captured["profile"].name == "balanced"
    assert captured["profile"].bits_per_channel == 3
    assert captured["recalibrate"] is True
    assert captured["calibration"] is True
    with pytest.raises(SystemExit):
        send._build_parser().parse_args(["file.bin", "--recalibrate", "--no-calibration"])

