def test_create_app_registers_receive_and_file_routes():
    from hdmi_exfil.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)

    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/api/receive/start" in rules
    assert "/api/receive/file/<path:filename>" in rules
    assert "/sender" in rules
    assert "/sender/app" in rules
    assert "/sender/page" in rules


def test_sender_routes_serve_standalone_sender_and_wrapper() -> None:
    from hdmi_exfil.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)
    client = app.test_client()

    sender = client.get("/sender")
    assert sender.status_code == 200
    assert b'<iframe id="sender-frame" src="/sender/app"' in sender.data

    sender_app = client.get("/sender/app")
    assert sender_app.status_code == 200
    assert b"Drop a file to send" in sender_app.data

    sender_page = client.get("/sender/page")
    assert sender_page.status_code == 200
    assert b'<iframe id="sender-frame" src="/sender/app"' in sender_page.data


def test_history_page_exposes_filters_and_static_script() -> None:
    from hdmi_exfil.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)
    client = app.test_client()

    history_page = client.get("/history")
    assert history_page.status_code == 200
    assert b"Search files, paths or protocols" in history_page.data
    assert b"All statuses" in history_page.data
    assert b'/static/history.js' in history_page.data

    history_script = client.get("/static/history.js")
    assert history_script.status_code == 200
    assert b"hdmi_exfil_history_filters" in history_script.data
    assert b"Clear the local browser history log?" in history_script.data


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


def test_shutdown_runtime_stops_worker_and_releases_capture() -> None:
    from hdmi_exfil.interfaces.web.app_factory import create_app, shutdown_runtime

    class FakeWorker:
        def __init__(self) -> None:
            self.stop_calls = 0

        def is_alive(self) -> bool:
            return True

        def stop(self) -> None:
            self.stop_calls += 1

    class FakeCaptureManager:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self) -> None:
            self.release_calls += 1

    app = create_app(runtime=False)
    worker = FakeWorker()
    capture_manager = FakeCaptureManager()
    app._receiver_worker = worker
    app._capture_manager = capture_manager

    shutdown_runtime(app)

    assert worker.stop_calls == 1
    assert capture_manager.release_calls == 1
    assert app._receiver_worker is None
