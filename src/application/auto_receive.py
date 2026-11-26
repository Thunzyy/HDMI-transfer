"""Auto receive: keep a receiver worker armed for the active sender profile.

Each worker receives one file and ends. The supervisor looks at how the last
worker it started ended and decides: re-arm after a completed file, count a
failure otherwise, and pause after too many failures in a row so a missing
signal or device never turns into a busy loop.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

# Worker states in which nothing has been received yet, so restarting is harmless.
_IDLE_STATES = frozenset({
    "idle", "opening", "probing", "waiting", "preflight_wait", "no_signal", "fallback",
})
_NEUTRAL_STOPS = frozenset({"supervisor", "replaced"})


class AutoReceiveSupervisor:
    def __init__(
        self,
        store,
        start_worker: Callable[[dict], object],
        get_worker: Callable[[], object | None],
        *,
        rearm_delay_s: float = 1.0,
        max_failures: int = 3,
        clock: Callable[[], float] = time.monotonic,
        interval_s: float = 0.5,
    ) -> None:
        self._store = store
        self._start_worker = start_worker
        self._get_worker = get_worker
        self._rearm_delay_s = rearm_delay_s
        self._max_failures = max_failures
        self._clock = clock
        self._interval_s = interval_s
        self._lock = threading.RLock()
        self._paused = False
        self._reason = ""
        self._failures = 0
        self._own_worker = None
        self._judged = True
        self._rearm_at = 0.0
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    # -- control ----------------------------------------------------------

    def pause(self, reason: str) -> None:
        with self._lock:
            self._paused, self._reason = True, reason

    def clear_pause(self) -> None:
        with self._lock:
            self._paused, self._reason, self._failures = False, "", 0

    def on_profile_changed(self) -> None:
        """New settings: clear any pause and restart an armed worker that is still idle."""
        with self._lock:
            self.clear_pause()
            worker = self._own_worker
            if worker is not None and worker.is_alive():
                state = (worker.get_runtime_state() or {}).get("state")
                if state in _IDLE_STATES:
                    worker.stop(reason="supervisor")

    def adopt_match(self, worker) -> None:
        """Make the profile whose calibration matched the live signal the active one."""
        if worker is None:
            return
        matched = (worker.get_runtime_state() or {}).get("matched_profile_id")
        if matched is None or self._store.get_active_id() == matched:
            return
        if self._store.get(matched) is None:
            return
        log.info("Auto receive: signal matched sender profile %s, switching", matched)
        self._store.set_active_id(matched)

    def status(self) -> dict:
        with self._lock:
            worker = self._own_worker
            return {
                "enabled": bool(self._store.get_auto_receive()),
                "paused": self._paused,
                "reason": self._reason,
                "consecutive_failures": self._failures,
                "armed": bool(worker is not None and worker.is_alive()),
            }

    # -- decision step ----------------------------------------------------

    def _fail(self, message: str) -> None:
        self._failures += 1
        log.warning("Auto receive: %s (%d in a row)", message, self._failures)
        if self._failures >= self._max_failures:
            self.pause(f"{self._failures} receptions failed in a row")

    def _judge_last(self) -> None:
        worker = self._own_worker
        if worker is None or self._judged:
            return
        self._judged = True
        if getattr(worker, "stop_reason", None) in _NEUTRAL_STOPS:
            return
        state = (worker.get_runtime_state() or {}).get("state")
        if state == "complete":
            self._failures = 0
            self._rearm_at = self._clock() + self._rearm_delay_s
        else:
            self._fail(f"reception ended without a file (state: {state})")

    def tick(self) -> None:
        with self._lock:
            current = self._get_worker()
            if current is not None and current.is_alive():
                self.adopt_match(current)
                return
            self._judge_last()
            if self._paused or not self._store.get_auto_receive():
                return
            profile_id = self._store.get_active_id()
            profile = self._store.get(profile_id) if profile_id is not None else None
            if profile is None or self._clock() < self._rearm_at:
                return
            try:
                self._own_worker = self._start_worker(profile)
                self._judged = False
            except Exception as exc:  # a missing device must not kill the supervisor
                self._own_worker = None
                self._fail(f"could not start ({exc})")

    # -- thread -----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="auto-receive", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._shutdown.wait(self._interval_s):
            try:
                self.tick()
            except Exception:
                log.exception("Auto receive tick failed")

    def shutdown(self) -> None:
        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
