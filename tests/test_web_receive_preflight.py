from __future__ import annotations

from dataclasses import replace

import cv2

import hdmi_transfer.interfaces.web.app_factory as server
from hdmi_transfer.core.config import PROFILES


class _FakeRegistry:
    def __init__(self, device: dict) -> None:
        self._device = device

    def get_backend(self, device_idx: int) -> int | None:
        if device_idx != self._device["index"]:
            return None
        return self._device["backend"]

    def get_device(self, device_idx: int) -> dict | None:
        if device_idx != self._device["index"]:
            return None
        return dict(self._device)

    def list_devices(self) -> list[dict]:
        return [dict(self._device)]


class _FakeCaptureManager:
    def release(self) -> None:
        return None

    def wait_until_ready(self, timeout: float = 0.0) -> bool:
        return False

    def take(self, device: int):
        return None, None

    def return_capture(self, **kwargs) -> None:
        return None


def test_api_receive_start_passes_explicit_preflight_flag(monkeypatch, tmp_path) -> None:
    app = server.create_app(output_dir=str(tmp_path), runtime=False)
    app._device_registry = _FakeRegistry({
        "index": 4,
        "name": "Elgato 4K X",
        "backend": int(cv2.CAP_MSMF),
        "msmf_index": 4,
    })
    app._capture_manager = _FakeCaptureManager()
    captured: dict[str, object] = {}

    class FakeWorker:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def start(self) -> None:
            return None

    monkeypatch.setattr("hdmi_transfer.web.receiver_worker.ReceiverWorker", FakeWorker)
    client = app.test_client()

    response = client.post("/api/receive/start", json={
        "device": 4,
        "profile": "balanced",
        "mode": "sequential",
        "bpc": 1,
        "preflight": True,
    })

    assert response.status_code == 200
    assert response.json == {"status": "started"}
    assert captured["device"] == 4
    assert captured["mode"] == "sequential"
    assert captured["profile"] == replace(PROFILES["balanced"], bits_per_channel=1)
    assert captured["require_preflight"] is True


def test_api_receive_status_exposes_runtime_preflight_state(monkeypatch, tmp_path) -> None:
    app = server.create_app(output_dir=str(tmp_path), runtime=False)

    class FakeWorker:
        def is_alive(self) -> bool:
            return True

        def get_preview_health(self) -> dict[str, object]:
            return {"preview_seq": 12, "preview_age_s": 0.4}

        def get_runtime_state(self) -> dict[str, object]:
            return {
                "state": "preflight_wait",
                "protocol": "sequential",
                "preflight_required": True,
                "preflight_state": "waiting",
                "preflight_stage": "transfer",
                "requested_transfer_bpc": 3,
                "transfer_bpc": None,
            }

    app._receiver_worker = FakeWorker()
    client = app.test_client()

    response = client.get("/api/receive/status")

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert response.json == {
        "active": True,
        "preview_seq": 12,
        "preview_age_s": 0.4,
        "state": "preflight_wait",
        "protocol": "sequential",
        "preflight_required": True,
        "preflight_state": "waiting",
        "preflight_stage": "transfer",
        "requested_transfer_bpc": 3,
        "transfer_bpc": None,
    }


def test_api_receive_status_preserves_terminal_state_after_worker_exit(monkeypatch, tmp_path) -> None:
    app = server.create_app(output_dir=str(tmp_path), runtime=False)

    class FakeWorker:
        def is_alive(self) -> bool:
            return False

        def get_preview_health(self) -> dict[str, object]:
            return {"preview_seq": 88, "preview_age_s": 1.2}

        def get_runtime_state(self) -> dict[str, object]:
            return {
                "state": "complete",
                "protocol": "fountain",
                "filename": "payload.bin",
                "download_url": "/api/receive/download/payload.bin",
                "speed_mbps": 4.2,
                "preflight_required": True,
                "preflight_state": "ok",
                "preflight_stage": "done",
                "requested_transfer_bpc": 2,
                "transfer_bpc": 1,
            }

    app._receiver_worker = FakeWorker()
    client = app.test_client()

    response = client.get("/api/receive/status")

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert response.json == {
        "active": False,
        "preview_seq": 88,
        "preview_age_s": 1.2,
        "state": "complete",
        "protocol": "fountain",
        "filename": "payload.bin",
        "download_url": "/api/receive/download/payload.bin",
        "speed_mbps": 4.2,
        "preflight_required": True,
        "preflight_state": "ok",
        "preflight_stage": "done",
        "requested_transfer_bpc": 2,
        "transfer_bpc": 1,
    }
