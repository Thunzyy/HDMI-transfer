from __future__ import annotations

import time

import pytest

import tests.test_web_e2e_hardware as hardware


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code == 200

    def json(self) -> dict[str, object]:
        return dict(self._payload)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_wait_for_receiver_completion_returns_metrics_from_runtime_status(monkeypatch) -> None:
    monkeypatch.setattr(
        hardware.requests,
        "get",
        lambda url, timeout=0: _FakeResponse({
            "active": False,
            "state": "complete",
            "filename": "payload.bin",
            "size": 1024,
            "sha256_ok": True,
            "sha256_available": True,
            "duration_s": 1.25,
            "speed_mbps": 6.5,
            "download_url": "/api/receive/download/payload.bin",
        }),
    )

    result = hardware._wait_for_receiver_completion(
        driver=object(),
        base_url="http://127.0.0.1:5000",
        timeout_s=1.0,
        sender_debug={"status": "Transmitting"},
        stall_timeout_s=0.1,
        poll_interval_s=0.0,
    )

    assert result == {
        "name": "payload.bin",
        "size": "1024",
        "sha": "OK",
        "duration": "1.25 s",
        "speed": "6.50 Mbps",
        "download": "/api/receive/download/payload.bin",
    }


def test_wait_for_receiver_completion_fails_fast_on_preflight_stall(monkeypatch) -> None:
    monkeypatch.setattr(
        hardware.requests,
        "get",
        lambda url, timeout=0: _FakeResponse({
            "active": True,
            "state": "preflight_wait",
            "message": "Waiting for HDMI preflight frame...",
            "preflight_required": True,
            "preflight_state": "waiting",
            "frames_captured": 120,
        }),
    )
    monkeypatch.setattr(
        hardware,
        "_receiver_debug_state",
        lambda driver: {"status": "Waiting for HDMI preflight frame...", "logs": ["preflight"]},
    )

    started = time.perf_counter()
    with pytest.raises(AssertionError, match="preflight"):
        hardware._wait_for_receiver_completion(
            driver=object(),
            base_url="http://127.0.0.1:5000",
            timeout_s=1.0,
            sender_debug={"status": "Transmitting", "frames": "42"},
            stall_timeout_s=0.05,
            poll_interval_s=0.0,
        )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5


def test_wait_for_receiver_completion_fails_fast_on_preflight_even_if_frames_change(monkeypatch) -> None:
    states = iter([
        {
            "active": True,
            "state": "preflight_wait",
            "message": "Waiting for HDMI preflight frame... (10 frames scanned)",
            "preflight_required": True,
            "preflight_state": "waiting",
            "frames_captured": 10,
            "preview_seq": 10,
        },
        {
            "active": True,
            "state": "preflight_wait",
            "message": "Waiting for HDMI preflight frame... (20 frames scanned)",
            "preflight_required": True,
            "preflight_state": "waiting",
            "frames_captured": 20,
            "preview_seq": 20,
        },
        {
            "active": True,
            "state": "preflight_wait",
            "message": "Waiting for HDMI preflight frame... (30 frames scanned)",
            "preflight_required": True,
            "preflight_state": "waiting",
            "frames_captured": 30,
            "preview_seq": 30,
        },
    ])

    def fake_get(url, timeout=0):
        try:
            return _FakeResponse(next(states))
        except StopIteration:
            return _FakeResponse({
                "active": True,
                "state": "preflight_wait",
                "message": "Waiting for HDMI preflight frame... (40 frames scanned)",
                "preflight_required": True,
                "preflight_state": "waiting",
                "frames_captured": 40,
                "preview_seq": 40,
            })

    monkeypatch.setattr(hardware.requests, "get", fake_get)
    monkeypatch.setattr(
        hardware,
        "_receiver_debug_state",
        lambda driver: {"status": "Waiting for HDMI preflight frame...", "logs": ["preflight"]},
    )

    started = time.perf_counter()
    with pytest.raises(AssertionError, match="preflight"):
        hardware._wait_for_receiver_completion(
            driver=object(),
            base_url="http://127.0.0.1:5000",
            timeout_s=1.0,
            sender_debug={"status": "Transmitting", "frames": "42"},
            stall_timeout_s=10.0,
            preflight_timeout_s=0.05,
            poll_interval_s=0.0,
        )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5


def test_wait_for_receiver_completion_fails_fast_on_stalled_preflight_preview(monkeypatch) -> None:
    monkeypatch.setattr(
        hardware.requests,
        "get",
        lambda url, timeout=0: _FakeResponse({
            "active": True,
            "state": "preflight_wait",
            "message": "Waiting for HDMI preflight frame...",
            "preflight_required": True,
            "preflight_state": "waiting",
            "preview_seq": 4,
            "preview_age_s": 5.0,
            "low_signal_detected": False,
        }),
    )
    monkeypatch.setattr(
        hardware,
        "_receiver_debug_state",
        lambda driver: {"status": "Waiting for HDMI preflight frame...", "logs": ["preview stalled"]},
    )

    started = time.perf_counter()
    with pytest.raises(AssertionError, match="preview"):
        hardware._wait_for_receiver_completion(
            driver=object(),
            base_url="http://127.0.0.1:5000",
            timeout_s=1.0,
            sender_debug={"status": "Preflight", "frames": "99"},
            stall_timeout_s=10.0,
            preflight_timeout_s=10.0,
            poll_interval_s=0.0,
        )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5


def test_wait_for_receiver_completion_allows_longer_preflight_while_sender_negotiates(
    monkeypatch,
) -> None:
    states = iter([
        {
            "active": True,
            "state": "preflight_wait",
            "message": "Waiting for HDMI preflight frame... (10 frames scanned)",
            "preflight_required": True,
            "preflight_state": "waiting",
            "preflight_stage": "path",
            "frames_captured": 10,
            "preview_seq": 10,
        },
        {
            "active": True,
            "state": "preflight_wait",
            "message": "Waiting for transfer bpc calibration... (20 frames scanned)",
            "preflight_required": True,
            "preflight_state": "waiting",
            "preflight_stage": "transfer",
            "frames_captured": 20,
            "preview_seq": 20,
        },
        {
            "active": False,
            "state": "complete",
            "filename": "payload.bin",
            "size": 1024,
            "sha256_ok": True,
            "sha256_available": True,
            "duration_s": 1.25,
            "speed_mbps": 6.5,
            "download_url": "/api/receive/download/payload.bin",
        },
    ])

    def fake_get(url, timeout=0):
        time.sleep(0.03)
        try:
            return _FakeResponse(next(states))
        except StopIteration:
            return _FakeResponse({
                "active": False,
                "state": "complete",
                "filename": "payload.bin",
                "size": 1024,
                "sha256_ok": True,
                "sha256_available": True,
                "duration_s": 1.25,
                "speed_mbps": 6.5,
                "download_url": "/api/receive/download/payload.bin",
            })

    monkeypatch.setattr(hardware.requests, "get", fake_get)

    result = hardware._wait_for_receiver_completion(
        driver=object(),
        base_url="http://127.0.0.1:5000",
        timeout_s=1.0,
        sender_debug={"status": "Preflight", "frames": "180"},
        stall_timeout_s=10.0,
        preflight_timeout_s=0.05,
        poll_interval_s=0.0,
    )

    assert result["name"] == "payload.bin"
    assert result["sha"] == "OK"
