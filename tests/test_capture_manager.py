"""Tests for centralized capture lifecycle management."""

from __future__ import annotations

import threading

import pytest


class _ObservedLock:
    """Expose acquisition attempts so concurrency assertions need no sleeps."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.attempted = threading.Event()

    def __enter__(self):
        self.attempted.set()
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


def _start_call(callback):
    done = threading.Event()
    errors = []

    def run():
        try:
            callback()
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, done, errors


class _FakeCapture:
    def __init__(self, *, opened: bool = True) -> None:
        self._opened = opened
        self.released = False

    def isOpened(self) -> bool:
        return self._opened

    def release(self) -> None:
        self.released = True
        self._opened = False


def test_capture_manager_reuses_matching_persistent_handle() -> None:
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    capture = _FakeCapture()
    manager = CaptureManager()

    manager.prime(device=1, backend=42, capture=capture)
    taken_capture, backend = manager.take(device=1)

    assert taken_capture is capture
    assert backend == 42


def test_capture_manager_release_clears_persistent_handle() -> None:
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    capture = _FakeCapture()
    manager = CaptureManager()
    manager.prime(device=2, backend=24, capture=capture)

    manager.release()

    taken_capture, backend = manager.take(device=2)
    assert taken_capture is None
    assert backend is None
    assert capture.released is True


def test_capture_manager_opens_distinct_open_source_for_logical_device() -> None:
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    calls = []
    capture = _FakeCapture()

    def opener(device, backend, width, height, fps):
        calls.append((device, backend, width, height, fps))
        return capture

    manager = CaptureManager(opener=opener)

    manager.prime(device=7, open_device=1, backend=42)
    taken_capture, backend = manager.take(device=7)

    assert calls == [(1, 42, 1920, 1080, 60)]
    assert taken_capture is capture
    assert backend == 42


def test_capture_manager_accepts_named_open_source() -> None:
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    calls = []
    capture = _FakeCapture()

    def opener(device, backend, width, height, fps):
        calls.append((device, backend, width, height, fps))
        return capture

    manager = CaptureManager(opener=opener)

    manager.prime(
        device=7,
        open_device="ffmpeg-dshow:Elgato 4K X",
        backend=42,
    )
    taken_capture, backend = manager.take(device=7)

    assert calls == [("ffmpeg-dshow:Elgato 4K X", 42, 1920, 1080, 60)]
    assert taken_capture is capture
    assert backend == 42


def test_release_waits_for_inflight_open_and_discards_its_capture() -> None:
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    entered = threading.Event()
    finish_open = threading.Event()
    capture = _FakeCapture()

    def opener(*args):
        entered.set()
        assert finish_open.wait(3)
        return capture

    manager = CaptureManager(opener=opener)
    operation_lock = _ObservedLock()
    manager._operation_lock = operation_lock
    prime_thread, prime_done, prime_errors = _start_call(
        lambda: manager.prime(device=0, open_device=2, backend=700),
    )
    assert entered.wait(2)
    operation_lock.attempted.clear()
    release_thread, release_done, release_errors = _start_call(manager.release)
    try:
        assert operation_lock.attempted.wait(2)
        assert not release_done.is_set()
        assert not manager.wait_until_ready(timeout=0)
    finally:
        finish_open.set()
        prime_thread.join(timeout=3)
        release_thread.join(timeout=3)

    assert prime_done.is_set() and release_done.is_set()
    assert prime_errors == release_errors == []
    assert capture.released
    assert not manager.is_primed(device=0)
    assert manager.wait_until_ready(timeout=0)


def _defer_prime_threads(monkeypatch):
    from hdmi_transfer.adapters.capture import capture_manager

    scheduled = []

    class DeferredThread:
        def __init__(self, *, target, kwargs, daemon):
            self.target = target
            self.kwargs = kwargs

        def start(self):
            scheduled.append(lambda: self.target(**self.kwargs))

    monkeypatch.setattr(capture_manager.threading, "Thread", DeferredThread)
    return scheduled


@pytest.mark.parametrize("handoff", ["release", "take"])
def test_handoff_cancels_prime_before_background_thread_starts(monkeypatch, handoff):
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    scheduled = _defer_prime_threads(monkeypatch)
    calls = []
    manager = CaptureManager(opener=lambda *args: calls.append(args))
    manager.prime_async(device=0, open_device=2, backend=700)
    assert not manager.wait_until_ready(timeout=0)

    if handoff == "release":
        manager.release()
    else:
        assert manager.take(device=0) == (None, None)
    scheduled[0]()

    assert calls == []
    assert not manager.is_primed(device=0)
    assert manager.wait_until_ready(timeout=0)


def test_newest_queued_prime_supersedes_older_requests(monkeypatch):
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    scheduled = _defer_prime_threads(monkeypatch)
    calls = []
    capture = _FakeCapture()

    def opener(*args):
        calls.append(args)
        return capture

    manager = CaptureManager(opener=opener)
    manager.prime_async(device=0, open_device=2, backend=700)
    manager.prime_async(device=1, open_device=3, backend=700)
    scheduled[0]()
    assert calls == []
    assert not manager.wait_until_ready(timeout=0)
    scheduled[1]()

    assert [args[0] for args in calls] == [3]
    assert manager.take(device=1) == (capture, 700)
    assert not capture.released


def test_release_also_cancels_requests_queued_while_old_open_drains(monkeypatch):
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    entered = threading.Event()
    finish_open = threading.Event()
    capture = _FakeCapture()
    calls = []

    def opener(*args):
        calls.append(args)
        entered.set()
        assert finish_open.wait(3)
        return capture

    manager = CaptureManager(opener=opener)
    operation_lock = _ObservedLock()
    manager._operation_lock = operation_lock
    prime_thread, prime_done, prime_errors = _start_call(
        lambda: manager.prime(device=0, open_device=2, backend=700),
    )
    assert entered.wait(2)
    operation_lock.attempted.clear()
    release_thread, release_done, release_errors = _start_call(manager.release)
    try:
        assert operation_lock.attempted.wait(2)
        scheduled = _defer_prime_threads(monkeypatch)
        manager.prime_async(device=1, open_device=3, backend=700)
    finally:
        finish_open.set()
        prime_thread.join(timeout=3)
        release_thread.join(timeout=3)

    assert prime_done.is_set() and release_done.is_set()
    assert prime_errors == release_errors == []
    scheduled[0]()
    assert [args[0] for args in calls] == [2]
    assert capture.released
    assert manager.take(device=1) == (None, None)
    assert manager.wait_until_ready(timeout=0)


def test_replacement_releases_superseded_open_before_opening_next_device():
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    first_entered = threading.Event()
    finish_first = threading.Event()
    second_entered = threading.Event()
    finish_second = threading.Event()
    first_capture = _FakeCapture()
    second_capture = _FakeCapture()

    def opener(source, *args):
        if source == 2:
            first_entered.set()
            assert finish_first.wait(3)
            return first_capture
        assert first_capture.released
        second_entered.set()
        assert finish_second.wait(3)
        return second_capture

    manager = CaptureManager(opener=opener)
    manager.prime_async(device=0, open_device=2, backend=700)
    assert first_entered.wait(2)
    manager.prime_async(device=1, open_device=3, backend=700)
    try:
        assert not second_entered.is_set()
        finish_first.set()
        assert second_entered.wait(2)
        assert not manager.wait_until_ready(timeout=0)
    finally:
        finish_first.set()
        finish_second.set()

    assert manager.wait_until_ready(timeout=2)
    assert manager.take(device=1) == (second_capture, 700)
    assert first_capture.released
    assert not second_capture.released


def test_take_waits_for_current_open_and_transfers_ownership():
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    entered = threading.Event()
    finish_open = threading.Event()
    capture = _FakeCapture()

    def opener(*args):
        entered.set()
        assert finish_open.wait(3)
        return capture

    manager = CaptureManager(opener=opener)
    operation_lock = _ObservedLock()
    manager._operation_lock = operation_lock
    manager.prime_async(device=0, open_device=2, backend=700)
    assert entered.wait(2)
    operation_lock.attempted.clear()
    result = []
    take_thread, take_done, errors = _start_call(
        lambda: result.append(manager.take(device=0)),
    )
    try:
        assert operation_lock.attempted.wait(2)
        assert not take_done.is_set()
    finally:
        finish_open.set()
        take_thread.join(timeout=3)

    assert take_done.is_set() and errors == []
    assert result == [(capture, 700)]
    manager.release()
    assert not capture.released  # The receiving worker owns it now.


def test_release_cancels_prime_waiting_for_registry_without_lock_inversion():
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    registry_lock = _ObservedLock()
    registry_lock.lock.acquire()
    operation_lock = _ObservedLock()
    calls = []
    manager = CaptureManager(
        opener=lambda *args: calls.append(args), open_lock=registry_lock,
    )
    manager._operation_lock = operation_lock
    manager.prime_async(device=0, open_device=2, backend=700)
    assert registry_lock.attempted.wait(2)
    operation_lock.attempted.clear()
    release_thread, release_done, errors = _start_call(manager.release)
    try:
        assert operation_lock.attempted.wait(2)
        assert not release_done.is_set()
    finally:
        registry_lock.lock.release()
        release_thread.join(timeout=3)

    assert release_done.is_set() and errors == []
    assert calls == []
    assert manager.wait_until_ready(timeout=0)
    assert not manager.is_primed(device=0)


def test_failed_open_releases_previous_capture_and_restores_ready():
    from hdmi_transfer.adapters.capture.capture_manager import CaptureManager

    def opener(*args):
        raise RuntimeError("device unavailable")

    manager = CaptureManager(opener=opener)
    previous = _FakeCapture()
    manager.prime(device=0, backend=700, capture=previous)
    with pytest.raises(RuntimeError, match="device unavailable"):
        manager.prime(device=0, open_device=2, backend=700)

    assert previous.released
    assert manager.wait_until_ready(timeout=0)
    assert manager.take(device=0) == (None, None)
