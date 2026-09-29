from __future__ import annotations

import contextlib
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import tools.hardware_ui_benchmark as benchmark
from tools.hardware_ui_benchmark import BenchmarkCase, _build_sender_url


def test_build_sender_url_includes_receiver_api_base_url() -> None:
    url = _build_sender_url(
        "http://127.0.0.1:62076",
        "payload.bin",
        BenchmarkCase("fountain_bpc2_r1.50", "fountain", 2, fountain_redundancy=1.5),
        api_base_url="http://127.0.0.1:62075",
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:62076"
    assert params["apiBaseUrl"] == ["http://127.0.0.1:62075"]


def test_wait_for_case_result_checks_receiver_before_output_file(monkeypatch, tmp_path: Path) -> None:
    call_order: list[str] = []
    output_file = tmp_path / "payload.bin"
    output_file.write_bytes(b"ok")

    monkeypatch.setattr(
        benchmark,
        "_wait_for_receiver_completion",
        lambda *args, **kwargs: call_order.append("receiver") or {
            "name": "payload.bin",
            "size": "2",
            "sha": "OK",
            "duration": "1.00 s",
            "speed": "8.00 Mbps",
            "download": "/api/receive/download/payload.bin",
        },
    )
    monkeypatch.setattr(
        benchmark,
        "_wait_for_output_file",
        lambda *args, **kwargs: call_order.append("output") or output_file,
    )

    metrics, completed_output, duration_s = benchmark._wait_for_case_result(
        receiver_driver=object(),
        base_url="http://127.0.0.1:62075",
        output_dir=tmp_path,
        known_files=set(),
        sender_url="http://127.0.0.1:62076/sender.html",
        sender_debug={"sender_url": "http://127.0.0.1:62076/sender.html"},
        completion_timeout_s=5.0,
        output_timeout_s=5.0,
    )

    assert call_order == ["receiver", "output"]
    assert metrics["download"] == "/api/receive/download/payload.bin"
    assert completed_output == output_file
    assert duration_s >= 0.0


def test_wait_for_case_result_tolerates_missing_output_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        benchmark,
        "_wait_for_receiver_completion",
        lambda *args, **kwargs: {
            "name": "payload.bin",
            "size": "2",
            "sha": "OK",
            "duration": "1.00 s",
            "speed": "8.00 Mbps",
            "download": "/api/receive/download/payload.bin",
        },
    )
    monkeypatch.setattr(
        benchmark,
        "_wait_for_output_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )

    metrics, completed_output, duration_s = benchmark._wait_for_case_result(
        receiver_driver=object(),
        base_url="http://127.0.0.1:62075",
        output_dir=tmp_path,
        known_files=set(),
        sender_url="http://127.0.0.1:62076/sender.html",
        sender_debug={"sender_url": "http://127.0.0.1:62076/sender.html"},
        completion_timeout_s=5.0,
        output_timeout_s=5.0,
    )

    assert metrics["name"] == "payload.bin"
    assert completed_output is None
    assert duration_s >= 0.0


def test_run_case_uses_browser_sender_session_instead_of_raw_launcher(
    monkeypatch, tmp_path: Path
) -> None:
    output_dir = tmp_path / "received"
    output_dir.mkdir()
    payload_path = tmp_path / "payload.bin"
    payload = b"payload-bytes"
    payload_path.write_bytes(payload)
    output_file = output_dir / payload_path.name
    output_file.write_bytes(payload)

    receiver_monitor = SimpleNamespace(x=0, y=0, width=1920, height=1080)
    sender_monitor = SimpleNamespace(x=1920, y=0, width=1920, height=1080)
    case = BenchmarkCase("sequential_bpc2_rep1", "sequential", 2, sequential_repeat=1)

    class DummyElement:
        def click(self) -> None:
            return None

    class DummyDriver:
        def __init__(self, name: str) -> None:
            self.name = name
            self.loaded_urls: list[str] = []

        def get(self, url: str) -> None:
            self.loaded_urls.append(url)

        def find_element(self, *args, **kwargs) -> DummyElement:
            return DummyElement()

    receiver_driver = DummyDriver("receiver")
    sender_driver = DummyDriver("sender")
    fullscreen_calls: list[tuple[object, object]] = []
    chrome_sessions: list[dict[str, object]] = []
    position_calls: list[tuple[str, object, int | None, int | None]] = []
    sender_debug_calls: list[object] = []
    session_drivers = iter([receiver_driver, sender_driver])

    @contextlib.contextmanager
    def fake_chrome_session(**kwargs):
        chrome_sessions.append(kwargs)
        yield next(session_drivers)

    monkeypatch.setattr(benchmark, "_select_receiver_monitor", lambda: receiver_monitor)
    monkeypatch.setattr(benchmark, "_chrome_session", fake_chrome_session)
    monkeypatch.setattr(
        benchmark,
        "_position_window",
        lambda driver, monitor, width=None, height=None: position_calls.append(
            (driver.name, monitor, width, height)
        ),
    )
    monkeypatch.setattr(benchmark, "_wait_for_ready_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_wait_for_receiver_devices", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_set_select_value", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_wait_for_receiver_stream_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_bring_to_front", lambda driver: None)
    monkeypatch.setattr(benchmark, "_terminate_process", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        benchmark,
        "_sender_debug_state",
        lambda driver: {"status": "transmitting", "driver": driver.name},
    )
    monkeypatch.setattr(
        benchmark,
        "_fullscreen_window",
        lambda driver, monitor: fullscreen_calls.append((driver, monitor)),
    )
    monkeypatch.setattr(
        benchmark,
        "_launch_sender_app",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy raw launcher should not be used")
        ),
    )
    monkeypatch.setattr(
        benchmark,
        "_wait_for_case_result",
        lambda **kwargs: (
            sender_debug_calls.append(kwargs["sender_debug"])
            or {
                "name": payload_path.name,
                "sha": "OK",
                "duration": "1.00 s",
                "speed": "8.00 Mbps",
                "download": "/api/receive/download/payload.bin",
            },
            output_file,
            1.0,
        ),
    )
    monkeypatch.setattr(benchmark, "_download_received_bytes", lambda *args, **kwargs: payload)
    monkeypatch.setattr(benchmark, "_reset_receiver", lambda *args, **kwargs: None)

    result = benchmark._run_case(
        base_url="http://127.0.0.1:62075",
        output_dir=output_dir,
        sender_base_url="http://127.0.0.1:62076",
        device_index=0,
        sender_monitor=sender_monitor,
        case=case,
        payload_path=payload_path,
        payload=payload,
    )

    assert result.ok is True
    assert len(chrome_sessions) == 2
    assert chrome_sessions[1]["app_url"].startswith("http://127.0.0.1:62076/sender.html?")
    assert sender_driver.loaded_urls == []
    assert fullscreen_calls == [(sender_driver, sender_monitor)]
    assert callable(sender_debug_calls[0])
    sender_state = sender_debug_calls[0]()
    assert sender_state == {"status": "transmitting", "driver": "sender"}


def test_run_case_ignores_reset_failures_after_result(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "received"
    output_dir.mkdir()
    payload_path = tmp_path / "payload.bin"
    payload = b"payload-bytes"
    payload_path.write_bytes(payload)
    output_file = output_dir / payload_path.name
    output_file.write_bytes(payload)

    receiver_monitor = SimpleNamespace(x=0, y=0, width=1920, height=1080)
    sender_monitor = SimpleNamespace(x=1920, y=0, width=1920, height=1080)
    case = BenchmarkCase("sequential_bpc2_rep1", "sequential", 2, sequential_repeat=1)

    class DummyElement:
        def click(self) -> None:
            return None

    class DummyDriver:
        def __init__(self, name: str) -> None:
            self.name = name
            self.loaded_urls: list[str] = []

        def get(self, url: str) -> None:
            self.loaded_urls.append(url)

        def find_element(self, *args, **kwargs) -> DummyElement:
            return DummyElement()

    receiver_driver = DummyDriver("receiver")
    sender_driver = DummyDriver("sender")
    session_drivers = iter([receiver_driver, sender_driver])

    @contextlib.contextmanager
    def fake_chrome_session(**kwargs):
        yield next(session_drivers)

    monkeypatch.setattr(benchmark, "_select_receiver_monitor", lambda: receiver_monitor)
    monkeypatch.setattr(benchmark, "_chrome_session", fake_chrome_session)
    monkeypatch.setattr(benchmark, "_position_window", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_wait_for_ready_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_wait_for_receiver_devices", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_set_select_value", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_wait_for_receiver_stream_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_bring_to_front", lambda *args, **kwargs: None)
    monkeypatch.setattr(benchmark, "_fullscreen_window", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        benchmark,
        "_wait_for_case_result",
        lambda **kwargs: (
            {
                "name": payload_path.name,
                "sha": "OK",
                "duration": "1.00 s",
                "speed": "8.00 Mbps",
                "download": "/api/receive/download/payload.bin",
            },
            output_file,
            1.0,
        ),
    )
    monkeypatch.setattr(benchmark, "_download_received_bytes", lambda *args, **kwargs: payload)
    monkeypatch.setattr(benchmark, "_sender_debug_state", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(benchmark, "_reset_receiver", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("reset failed")))

    result = benchmark._run_case(
        base_url="http://127.0.0.1:62075",
        output_dir=output_dir,
        sender_base_url="http://127.0.0.1:62076",
        device_index=0,
        sender_monitor=sender_monitor,
        case=case,
        payload_path=payload_path,
        payload=payload,
    )

    assert result.ok is True
