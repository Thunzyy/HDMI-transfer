def test_create_app_registers_receive_and_file_routes():
    from hdmi_exfil.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)

    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/api/receive/start" in rules
    assert "/api/receive/file/<path:filename>" in rules


def test_create_app_runtime_primes_persistent_capture_for_raw_dshow_source(monkeypatch):
    from hdmi_exfil.interfaces.web.app_factory import create_app

    cached_device = {
        "index": 0,
        "name": "Elgato 4K X",
        "backend": 1400,
        "dshow_index": 1,
        "prefer_dshow": True,
        "ffmpeg_dshow_name": "Elgato 4K X",
    }

    class FakeRegistry:
        def __init__(self, cache_file) -> None:
            self._devices = []
            self.open_lock = None

        def replace(self, devices):
            self._devices = list(devices)
            return self._devices

        def list_devices(self):
            return list(self._devices)

        def detect(self, detector):
            return self.replace(detector())

    class FakeCaptureManager:
        def __init__(self, **kwargs) -> None:
            self.prime_calls = []

        def prime_async(self, **kwargs) -> None:
            self.prime_calls.append(dict(kwargs))

    monkeypatch.setattr(
        "hdmi_exfil.interfaces.web.app_factory._load_disk_cache",
        lambda: [cached_device],
    )
    monkeypatch.setattr(
        "hdmi_exfil.adapters.capture.device_registry.DeviceRegistry",
        FakeRegistry,
    )
    monkeypatch.setattr(
        "hdmi_exfil.adapters.capture.capture_manager.CaptureManager",
        FakeCaptureManager,
    )
    monkeypatch.setattr(
        "hdmi_exfil.receiver.capture.source.open_capture",
        lambda *args, **kwargs: None,
    )

    app = create_app(runtime=True)

    assert app._capture_manager.prime_calls == [{
        "device": 0,
        "open_device": 1,
        "backend": 700,
    }]
