from __future__ import annotations

from unittest.mock import MagicMock, patch

import cv2


def test_resolve_capture_target_maps_logical_capture_card_to_dshow_index():
    from hdmi_exfil.adapters.capture.resolver import resolve_capture_target

    devices = [
        {
            "index": 0,
            "name": "Elgato 4K X",
            "width": 1920,
            "height": 1080,
            "fps": 60.0,
            "backend": int(cv2.CAP_MSMF),
            "dshow_index": 1,
            "prefer_dshow": True,
        },
    ]

    resolved = resolve_capture_target(0, detector=lambda: devices)

    assert resolved.logical_index == 0
    assert resolved.open_source == 1
    assert resolved.backend == int(cv2.CAP_DSHOW)
    assert resolved.device_name == "Elgato 4K X"
    assert resolved.auto_fixed is True
    assert resolved.fallback_targets == ((0, int(cv2.CAP_MSMF)),)
    assert "Elgato 4K X" in resolved.describe()


def test_resolve_capture_target_prefers_raw_dshow_index_over_named_ffmpeg_source():
    from hdmi_exfil.adapters.capture.resolver import resolve_capture_target

    devices = [
        {
            "index": 0,
            "name": "Elgato 4K X",
            "width": 1920,
            "height": 1080,
            "fps": 60.0,
            "backend": int(cv2.CAP_MSMF),
            "dshow_index": 3,
            "prefer_dshow": True,
            "ffmpeg_dshow_name": "Elgato 4K X",
        },
    ]

    resolved = resolve_capture_target(0, detector=lambda: devices)

    assert resolved.open_source == 3
    assert resolved.backend == int(cv2.CAP_DSHOW)
    assert resolved.fallback_targets == (
        ("ffmpeg-dshow:Elgato 4K X", int(cv2.CAP_DSHOW)),
        (0, int(cv2.CAP_MSMF)),
    )


def test_resolve_saved_capture_target_auto_heals_changed_logical_index():
    from hdmi_exfil.adapters.capture.resolver import resolve_saved_capture_target

    devices = [
        {
            "index": 2,
            "name": "Elgato 4K X",
            "width": 1920,
            "height": 1080,
            "fps": 60.0,
            "backend": int(cv2.CAP_MSMF),
            "dshow_index": 5,
            "prefer_dshow": True,
        },
    ]

    resolved = resolve_saved_capture_target(
        saved_name="Elgato 4K X",
        saved_index=0,
        detector=lambda: devices,
    )

    assert resolved.logical_index == 2
    assert resolved.open_source == 5
    assert resolved.backend == int(cv2.CAP_DSHOW)
    assert resolved.auto_fixed is True
    assert resolved.fallback_targets == ((2, int(cv2.CAP_MSMF)),)


def test_resolve_capture_target_raw_prefix_skips_detection():
    from hdmi_exfil.adapters.capture.resolver import resolve_capture_target

    def fail_detector():
        raise AssertionError("detector should not be called for raw: selectors")

    resolved = resolve_capture_target("raw:3", detector=fail_detector)

    assert resolved.open_source == 3
    assert resolved.backend is None
    assert resolved.forced_raw is True


def test_run_receive_uses_resolved_capture_target(monkeypatch, capsys):
    import hdmi_exfil.interfaces.cli.receive as receive
    from hdmi_exfil.adapters.capture.resolver import ResolvedCaptureTarget

    resolved = ResolvedCaptureTarget(
        requested_source="0",
        open_source=1,
        backend=int(cv2.CAP_DSHOW),
        logical_index=0,
        device_name="Elgato 4K X",
        width=1920,
        height=1080,
        fps=60.0,
        matched_by="logical_index",
        auto_fixed=True,
    )

    monkeypatch.setattr(receive, "resolve_capture_target", lambda source: resolved)

    opened: dict[str, object] = {}

    class FakeCaptureSource:
        def __init__(self, source, width, height, fps, backend=None):
            opened.update({
                "source": source,
                "width": width,
                "height": height,
                "fps": fps,
                "backend": backend,
            })
            self.actual_width = width
            self.actual_height = height
            self.actual_fps = fps

        def release(self):
            opened["released"] = True

    dispatched: dict[str, object] = {}

    monkeypatch.setattr(receive, "CaptureSource", FakeCaptureSource)
    monkeypatch.setattr(
        receive,
        "_run_receiver_worker",
        lambda resolved_source, mode, output, profile: dispatched.update({
            "resolved_source": resolved_source,
            "mode": mode,
            "output": output,
            "profile": profile,
        }),
    )

    receive.run_receive(
        source="0",
        mode="auto",
        profile=receive.PROFILES["balanced"],
        output="received_files",
    )

    assert opened == {
        "source": 1,
        "width": receive.PROFILES["balanced"].width,
        "height": receive.PROFILES["balanced"].height,
        "fps": receive.PROFILES["balanced"].target_fps,
        "backend": int(cv2.CAP_DSHOW),
        "released": True,
    }
    assert dispatched["resolved_source"] is resolved
    assert dispatched["mode"] == "auto"
    output = capsys.readouterr().out
    assert "Auto-fixed capture target" in output


def test_calibrate_open_capture_uses_resolved_capture_target(monkeypatch, capsys):
    import hdmi_exfil.interfaces.cli.calibrate as calibrate
    from hdmi_exfil.adapters.capture.resolver import ResolvedCaptureTarget

    resolved = ResolvedCaptureTarget(
        requested_source="0",
        open_source=4,
        backend=int(cv2.CAP_DSHOW),
        logical_index=0,
        device_name="Elgato 4K X",
        width=1920,
        height=1080,
        fps=60.0,
        matched_by="logical_index",
        auto_fixed=True,
    )

    monkeypatch.setattr(calibrate, "resolve_capture_target", lambda source: resolved)

    opened: dict[str, object] = {}

    class FakeCaptureSource:
        def __init__(self, source, width, height, fps, backend=None):
            opened.update({
                "source": source,
                "width": width,
                "height": height,
                "fps": fps,
                "backend": backend,
            })

    monkeypatch.setattr(calibrate, "CaptureSource", FakeCaptureSource)

    cap = calibrate._open_capture("0", profile=calibrate.PROFILES["balanced"])

    assert isinstance(cap, FakeCaptureSource)
    assert opened["source"] == 4
    assert opened["backend"] == int(cv2.CAP_DSHOW)
    assert "Auto-fixed capture target" in capsys.readouterr().out


@patch("hdmi_exfil.interfaces.cli.receiver_console.run_receive")
@patch("hdmi_exfil.interfaces.cli.receiver_console.resolve_saved_capture_target")
@patch("hdmi_exfil.interfaces.cli.receiver_console.settings")
def test_receiver_console_auto_updates_saved_device_index(
    mock_settings,
    mock_resolve_saved_target,
    mock_run_receive,
):
    from hdmi_exfil.adapters.capture.resolver import ResolvedCaptureTarget
    from hdmi_exfil.interfaces.cli.receiver_console import _action_receive

    mock_settings.load.return_value = {
        "receiver": {
            "device_name": "Elgato 4K X",
            "device_index": 0,
            "profile": "balanced",
            "mode": "auto",
            "output": "received_files",
        },
    }

    mock_resolve_saved_target.return_value = ResolvedCaptureTarget(
        requested_source=0,
        open_source=1,
        backend=int(cv2.CAP_DSHOW),
        logical_index=2,
        device_name="Elgato 4K X",
        width=1920,
        height=1080,
        fps=60.0,
        matched_by="saved_name",
        auto_fixed=True,
    )

    _action_receive()

    mock_settings.set_value.assert_called_once_with("receiver", "device_index", 2)
    mock_run_receive.assert_called_once()
    assert mock_run_receive.call_args.kwargs["source"] == "name:Elgato 4K X"
    assert mock_run_receive.call_args.kwargs["mode"] == "auto"
