def test_web_logo_and_favicon_are_served_from_images():
    from hdmi_transfer.interfaces.web.app_factory import create_app

    client = create_app(runtime=False).test_client()
    with client.get("/static/images/logo.svg") as logo:
        assert logo.status_code == 200
        assert logo.mimetype == "image/svg+xml"
        assert b"<svg" in logo.data
        logo_data = logo.data
    with client.get("/favicon.ico") as favicon:
        assert favicon.status_code == 200
        assert favicon.data == logo_data


def test_web_pages_load_shared_stylesheet():
    from hdmi_transfer.interfaces.web.app_factory import create_app

    client = create_app(runtime=False).test_client()
    response = client.get("/static/shared.css")
    assert response.status_code == 200
    assert response.mimetype == "text/css"
    assert b"--font-ui:" in response.data
    assert b".nav a.active{" in response.data
    for route in ("/", "/history", "/settings", "/sender", "/sender/test"):
        page = client.get(route)
        assert page.status_code == 200
        assert b'<link rel="stylesheet" href="/static/shared.css"' in page.data


def test_create_app_registers_receive_and_file_routes():
    from hdmi_transfer.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)

    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/api/receive/start" in rules
    assert "/api/receive/file/<path:filename>" in rules
    assert "/sender" in rules
    assert "/sender/app" in rules
    assert "/sender/page" in rules
    assert "/sender/test" in rules


def test_sender_routes_serve_standalone_sender_and_wrapper() -> None:
    from hdmi_transfer.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)
    client = app.test_client()

    sender = client.get("/sender")
    assert sender.status_code == 200
    assert b"Default 2-PC sender wrapper" in sender.data
    assert b"Open this page from the receiver host on the sender PC" in sender.data
    assert b'<iframe id="sender-frame" src="/sender/app"' in sender.data
    assert b"receiverApi=1" not in sender.data

    sender_app = client.get("/sender/app")
    assert sender_app.status_code == 200
    assert b"Drop files or a folder to send" in sender_app.data

    sender_page = client.get("/sender/page")
    assert sender_page.status_code == 200
    assert b"Default 2-PC sender wrapper" in sender_page.data
    assert b'<iframe id="sender-frame" src="/sender/app"' in sender_page.data
    assert b"receiverApi=1" not in sender_page.data

    sender_test = client.get("/sender/test")
    assert sender_test.status_code == 200
    assert b"Local 1-PC test wrapper" in sender_test.data
    assert b"single-PC validation" in sender_test.data
    assert b'<iframe id="sender-frame" src="/sender/app?receiverApi=1"' in sender_test.data


def test_history_page_exposes_filters_and_static_script() -> None:
    from hdmi_transfer.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)
    client = app.test_client()

    history_page = client.get("/history")
    assert history_page.status_code == 200
    assert b"Search files, paths or protocols" in history_page.data
    assert b"All statuses" in history_page.data
    assert b'/static/history.js' in history_page.data

    history_script = client.get("/static/history.js")
    assert history_script.status_code == 200
    assert b"hdmi_transfer_history_filters" in history_script.data
    assert b"Clear the local browser history log?" in history_script.data


def test_sender_app_uses_packaged_resources_without_repository_html(tmp_path, monkeypatch):
    from hdmi_transfer.interfaces.browser_sender import render_sender_html
    from hdmi_transfer.interfaces.web import app_factory

    # Model the installed-wheel location: no sender.html beside the package.
    monkeypatch.setattr(app_factory, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv("HDMI_EXFIL_ROOT", raising=False)
    client = app_factory.create_app(runtime=False).test_client()

    response = client.get("/sender/app")

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert response.get_data(as_text=True) == render_sender_html()
    assert "{{ SCRIPT_BODY }}" not in response.get_data(as_text=True)
    assert b"const FOUNTAIN_MAGIC" in response.data


def test_sender_app_keeps_explicit_standalone_document(tmp_path):
    from hdmi_transfer.interfaces.web.app_factory import create_app

    html = tmp_path / "sender.html"
    html.write_text("<!doctype html><title>Explicit sender</title>", encoding="utf-8")
    app = create_app(runtime=False)
    app.config["SENDER_HTML"] = str(html)

    with app.test_client().get("/sender/app") as response:
        assert response.status_code == 200
        assert response.get_data(as_text=True) == html.read_text(encoding="utf-8")


def test_create_app_runtime_primes_persistent_capture_for_raw_dshow_source(monkeypatch):
    from hdmi_transfer.interfaces.web.app_factory import create_app

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
            self._devices = [cached_device]
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
        "hdmi_transfer.adapters.capture.device_registry.DeviceRegistry",
        FakeRegistry,
    )
    monkeypatch.setattr(
        "hdmi_transfer.adapters.capture.capture_manager.CaptureManager",
        FakeCaptureManager,
    )
    monkeypatch.setattr(
        "hdmi_transfer.receiver.capture.source.open_capture",
        lambda *args, **kwargs: None,
    )

    app = create_app(runtime=True)

    assert app._capture_manager.prime_calls == [{
        "device": 0,
        "open_device": 1,
        "backend": 700,
    }]


def test_shutdown_runtime_stops_worker_and_releases_capture() -> None:
    from hdmi_transfer.interfaces.web.app_factory import create_app, shutdown_runtime

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
