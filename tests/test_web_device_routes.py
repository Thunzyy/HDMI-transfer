from __future__ import annotations

import cv2

import hdmi_exfil.web.server as server


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
    def __init__(self) -> None:
        self.prime_async_calls: list[dict] = []

    def is_primed(self, *, device: int) -> bool:
        return False

    def prime_async(self, **kwargs) -> None:
        self.prime_async_calls.append(kwargs)


def test_api_warm_device_uses_dshow_open_index_for_dshow_only_device(monkeypatch):
    app = server.create_app(runtime=False)
    app._device_registry = _FakeRegistry({
        "index": 7,
        "name": "Elgato 4K X",
        "backend": int(cv2.CAP_DSHOW),
        "dshow_index": 1,
        "prefer_dshow": True,
    })
    app._capture_manager = _FakeCaptureManager()
    client = app.test_client()

    response = client.post("/api/devices/warm", json={"device": 7})

    assert response.status_code == 200
    assert response.json == {"status": "opening"}
    assert app._capture_manager.prime_async_calls == [{
        "device": 7,
        "open_device": 1,
        "backend": int(cv2.CAP_DSHOW),
    }]
