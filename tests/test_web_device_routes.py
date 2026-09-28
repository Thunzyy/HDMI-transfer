from __future__ import annotations

import cv2

import hdmi_transfer.interfaces.web.app_factory as server


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
        self.prime_calls: list[dict] = []
        self.release_calls = 0

    def is_primed(self, *, device: int) -> bool:
        return False

    def release(self) -> None:
        self.release_calls += 1

    def prime(self, **kwargs) -> None:
        self.prime_calls.append(kwargs)

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


def test_api_warm_device_prefers_raw_dshow_source_for_capture_card(monkeypatch):
    app = server.create_app(runtime=False)
    app._device_registry = _FakeRegistry({
        "index": 7,
        "name": "Elgato 4K X",
        "backend": int(cv2.CAP_MSMF),
        "dshow_index": 3,
        "prefer_dshow": True,
        "ffmpeg_dshow_name": "Elgato 4K X",
    })
    app._capture_manager = _FakeCaptureManager()
    client = app.test_client()

    response = client.post("/api/devices/warm", json={"device": 7})

    assert response.status_code == 200
    assert response.json == {"status": "opening"}
    assert app._capture_manager.prime_async_calls == [{
        "device": 7,
        "open_device": 3,
        "backend": int(cv2.CAP_DSHOW),
    }]


def test_api_devices_primes_persistent_capture_for_raw_dshow_capture_card(monkeypatch):
    app = server.create_app(runtime=False)
    app._device_registry = _FakeRegistry({
        "index": 0,
        "name": "Elgato 4K X",
        "backend": int(cv2.CAP_MSMF),
        "dshow_index": 3,
        "prefer_dshow": True,
        "ffmpeg_dshow_name": "Elgato 4K X",
    })
    app._capture_manager = _FakeCaptureManager()
    devices = [{
        "index": 0,
        "name": "Elgato 4K X",
        "backend": int(cv2.CAP_MSMF),
        "dshow_index": 3,
        "prefer_dshow": True,
        "ffmpeg_dshow_name": "Elgato 4K X",
    }]
    app._detect_and_cache = lambda: devices
    client = app.test_client()

    response = client.get("/api/devices?force=1")

    assert response.status_code == 200
    assert response.json == devices
    assert app._capture_manager.release_calls == 1
    assert app._capture_manager.prime_calls == [{
        "device": 0,
        "open_device": 3,
        "backend": int(cv2.CAP_DSHOW),
    }]
