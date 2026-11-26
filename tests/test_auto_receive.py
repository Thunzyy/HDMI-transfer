import pytest

from hdmi_transfer.adapters.profile_store import ProfileStore
from hdmi_transfer.application.auto_receive import AutoReceiveSupervisor


class FakeWorker:
    def __init__(self, profile):
        self.profile = profile
        self.alive = True
        self.state = "preflight_wait"
        self.stop_reason = None

    def is_alive(self):
        return self.alive

    def get_runtime_state(self):
        return {"state": self.state}

    def finish(self, state):
        self.state, self.alive = state, False

    def stop(self, reason="user"):
        self.stop_reason = self.stop_reason or reason
        self.alive = False


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    store = ProfileStore(tmp_path / "profiles.sqlite3")
    pc = store.create({"name": "PC BNP", "device_name": "Card", "device_index": 0})
    store.set_active_id(pc["id"])
    store.set_auto_receive(True)
    started = []
    current = {"worker": None}

    def start_worker(profile):
        worker = FakeWorker(profile)
        started.append(worker)
        current["worker"] = worker
        return worker

    clock = Clock()
    supervisor = AutoReceiveSupervisor(store, start_worker, lambda: current["worker"], clock=clock)
    return store, supervisor, started, current, clock


def test_arms_when_enabled_with_active_profile(env):
    store, supervisor, started, _, _ = env
    supervisor.tick()
    assert len(started) == 1
    assert started[0].profile["name"] == "PC BNP"
    assert supervisor.status()["armed"] is True
    supervisor.tick()
    assert len(started) == 1


def test_does_nothing_when_disabled_or_no_profile(env):
    store, supervisor, started, _, _ = env
    store.set_auto_receive(False)
    supervisor.tick()
    store.set_auto_receive(True)
    store.set_active_id(None)
    supervisor.tick()
    assert started == []


def test_rearms_after_complete_only_after_delay(env):
    _, supervisor, started, _, clock = env
    supervisor.tick()
    started[0].finish("complete")
    supervisor.tick()
    assert len(started) == 1
    clock.now += 1.0
    supervisor.tick()
    assert len(started) == 2


def test_pauses_after_three_failures(env):
    _, supervisor, started, _, clock = env
    for _ in range(3):
        supervisor.tick()
        started[-1].finish("error")
        clock.now += 1.0
    supervisor.tick()
    assert len(started) == 3
    status = supervisor.status()
    assert status["paused"] is True
    assert status["consecutive_failures"] == 3
    assert "3" in status["reason"]


def test_success_resets_failure_count(env):
    _, supervisor, started, _, clock = env
    supervisor.tick()
    started[-1].finish("error")
    supervisor.tick()
    started[-1].finish("error")
    supervisor.tick()
    started[-1].finish("complete")
    supervisor.tick()
    assert supervisor.status()["consecutive_failures"] == 0
    clock.now += 1.0
    supervisor.tick()
    assert len(started) == 4


def test_replaced_and_supervisor_stops_are_neutral(env):
    _, supervisor, started, current, _ = env
    supervisor.tick()
    started[-1].stop(reason="replaced")
    supervisor.tick()
    started[-1].stop(reason="supervisor")
    supervisor.tick()
    assert supervisor.status()["consecutive_failures"] == 0
    assert len(started) == 3


def test_manual_worker_is_left_alone(env):
    _, supervisor, started, current, _ = env
    manual = FakeWorker({"name": "manual"})
    current["worker"] = manual
    supervisor.tick()
    assert started == []
    manual.finish("error")
    supervisor.tick()
    assert len(started) == 1
    assert supervisor.status()["consecutive_failures"] == 0


def test_manual_pause_and_clear(env):
    _, supervisor, started, _, _ = env
    supervisor.pause("Stopped by user")
    supervisor.tick()
    assert started == []
    assert supervisor.status() == {
        "enabled": True, "paused": True, "reason": "Stopped by user",
        "consecutive_failures": 0, "armed": False,
    }
    supervisor.clear_pause()
    supervisor.tick()
    assert len(started) == 1


def test_start_failure_counts_and_does_not_raise(env):
    store, _, _, _, clock = env

    def broken(profile):
        raise RuntimeError("capture device missing")

    supervisor = AutoReceiveSupervisor(store, broken, lambda: None, clock=clock)
    for _ in range(3):
        supervisor.tick()
        clock.now += 1.0
    assert supervisor.status()["paused"] is True


def test_profile_change_restarts_an_idle_armed_worker(env):
    _, supervisor, started, _, _ = env
    supervisor.tick()
    supervisor.on_profile_changed()
    assert started[0].stop_reason == "supervisor"
    supervisor.tick()
    assert len(started) == 2


def test_profile_change_keeps_a_worker_that_is_receiving(env):
    _, supervisor, started, _, _ = env
    supervisor.tick()
    started[0].state = "receiving"
    supervisor.on_profile_changed()
    assert started[0].alive is True


def test_deleted_active_profile_stops_arming(env):
    store, supervisor, started, _, clock = env
    supervisor.tick()
    store.delete(store.get_active_id())
    started[0].finish("complete")
    clock.now += 5.0
    supervisor.tick()
    assert len(started) == 1
    assert supervisor.status()["armed"] is False


def test_profile_device_is_found_by_name_first():
    from hdmi_transfer.interfaces.web.routes_receive import resolve_profile_device

    devices = [{"index": 0, "name": "USB Camera"}, {"index": 1, "name": "Elgato 4K X"}]
    assert resolve_profile_device(devices, {"device_name": "Elgato 4K X", "device_index": 0}) == 1
    assert resolve_profile_device(devices, {"device_name": "Gone", "device_index": 0}) == 0
    assert resolve_profile_device(devices, {"device_name": "Gone", "device_index": None}) is None
    assert resolve_profile_device([], {"device_name": None, "device_index": 2}) == 2


def test_matched_profile_becomes_active(env):
    store, supervisor, started, current, _ = env
    perso = store.create({"name": "PC PERSO", "device_name": "Card", "device_index": 0})
    supervisor.tick()
    started[0].matched = perso["id"]
    started[0].get_runtime_state = lambda: {"state": "preflight_ok", "matched_profile_id": perso["id"]}
    supervisor.adopt_match(current["worker"])
    assert store.get_active_id() == perso["id"]
    assert started[0].alive is True


def test_unknown_matched_profile_is_ignored(env):
    store, supervisor, started, current, _ = env
    active = store.get_active_id()
    supervisor.tick()
    started[0].get_runtime_state = lambda: {"state": "preflight_ok", "matched_profile_id": 999}
    supervisor.adopt_match(current["worker"])
    assert store.get_active_id() == active


def test_disarm_stops_idle_worker_and_does_not_rearm_when_off(env):
    store, supervisor, started, _, _ = env
    supervisor.tick()
    store.set_auto_receive(False)
    supervisor.disarm()
    assert started[0].stop_reason == "supervisor"
    supervisor.tick()
    assert len(started) == 1


def test_saved_index_wins_when_two_devices_share_a_name():
    from hdmi_transfer.interfaces.web.routes_receive import resolve_profile_device

    devices = [{"index": 0, "name": "Elgato 4K X"}, {"index": 1, "name": "Webcam"},
               {"index": 2, "name": "Elgato 4K X"}]
    assert resolve_profile_device(devices, {"device_name": "Elgato 4K X", "device_index": 2}) == 2
    assert resolve_profile_device(devices, {"device_name": "Elgato 4K X", "device_index": 1}) == 0


def test_user_stop_is_not_counted_as_a_failure(env):
    _, supervisor, started, _, _ = env
    supervisor.tick()
    started[0].stop(reason="user")
    supervisor.pause("Stopped by user")
    supervisor.tick()
    assert supervisor.status()["consecutive_failures"] == 0


def _call_in_thread(fn, timeout=1.0):
    import threading

    done = threading.Event()
    threading.Thread(target=lambda: (fn(), done.set()), daemon=True).start()
    return done.wait(timeout)


def test_tick_does_not_hold_the_lock_while_starting(env):
    store, _, _, current, clock = env
    seen = {}

    def slow_start(profile):
        seen["status_free"] = _call_in_thread(lambda: supervisor.status())
        worker = FakeWorker(profile)
        current["worker"] = worker
        return worker

    supervisor = AutoReceiveSupervisor(store, slow_start, lambda: current["worker"], clock=clock)
    supervisor.tick()
    assert seen["status_free"] is True
    assert supervisor.status()["armed"] is True


def test_disarm_stops_the_worker_outside_the_lock(env):
    _, supervisor, started, _, _ = env
    supervisor.tick()
    seen = {}
    original_stop = started[0].stop

    def stop(reason="user"):
        seen["status_free"] = _call_in_thread(lambda: supervisor.status())
        original_stop(reason)

    started[0].stop = stop
    supervisor.disarm()
    assert seen["status_free"] is True


def test_skipped_start_is_not_a_failure(env):
    store, _, _, _, clock = env
    supervisor = AutoReceiveSupervisor(store, lambda profile: None, lambda: None, clock=clock)
    for _ in range(4):
        supervisor.tick()
    status = supervisor.status()
    assert status["consecutive_failures"] == 0
    assert status["paused"] is False
    assert status["armed"] is False


def test_last_identity_follows_completed_files(env):
    _, supervisor, started, _, clock = env
    assert supervisor.last_identity is None
    supervisor.tick()
    started[0].completed_identity = ("a.bin", 3, "f" * 64)
    started[0].finish("complete")
    supervisor.tick()
    assert supervisor.last_identity == ("a.bin", 3, "f" * 64)

