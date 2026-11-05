"""Centralized management of persistent capture handles."""

from __future__ import annotations

import threading
from typing import Any, Callable


CaptureOpener = Callable[[int | str, int, int, int, int], Any]


class CaptureManager:
    """Owns at most one persistent capture handle for reuse across sessions."""

    def __init__(
        self,
        *,
        opener: CaptureOpener | None = None,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        open_lock: threading.Lock | None = None,
    ) -> None:
        self._opener = opener
        self._width = width
        self._height = height
        self._fps = fps
        self._open_lock = open_lock
        self._lock = threading.Lock()
        # Opening a device must finish (including cancellation cleanup) before
        # another owner can take over. Never wait here while holding _lock.
        self._operation_lock = threading.Lock()
        self._generation = 0
        self._ready = threading.Event()
        self._ready.set()
        self._capture: Any | None = None
        self._device: int | None = None
        self._open_device: int | str | None = None
        self._backend: int | None = None

    @property
    def device(self) -> int | None:
        return self._device

    def is_primed(self, *, device: int) -> bool:
        with self._lock:
            return (
                self._device == device
                and self._capture is not None
                and self._capture.isOpened()
            )

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout=timeout)

    def prime(
        self,
        *,
        device: int,
        open_device: int | str | None = None,
        backend: int,
        capture: Any | None = None,
    ) -> None:
        """Store a ready capture or open one immediately."""
        generation = self._reserve_prime()
        self._prime_reserved(
            generation=generation, device=device, open_device=open_device,
            backend=backend, capture=capture,
        )

    def _reserve_prime(self) -> int:
        with self._lock:
            self._generation += 1
            self._ready.clear()
            return self._generation

    def _finish_request(self, generation: int) -> None:
        with self._lock:
            if generation == self._generation:
                self._ready.set()

    def _detach_locked(self) -> Any | None:
        capture = self._capture
        self._capture = None
        self._device = None
        self._open_device = None
        self._backend = None
        return capture

    def _prime_reserved(
        self,
        *,
        generation: int,
        device: int,
        open_device: int | str | None,
        backend: int,
        capture: Any | None = None,
    ) -> None:
        source_to_open = open_device if open_device is not None else device
        with self._operation_lock:
            try:
                with self._lock:
                    if generation != self._generation:
                        return
                    previous = self._detach_locked()
                if previous is not None:
                    previous.release()

                if capture is None:
                    if self._opener is None:
                        raise RuntimeError(
                            "CaptureManager requires an opener when capture is not provided",
                        )
                    if self._open_lock is None:
                        capture = self._opener(
                            source_to_open, backend, self._width, self._height, self._fps,
                        )
                    else:
                        with self._open_lock:
                            # A release may have cancelled us while detection
                            # held the registry lock. Do not open a stale request.
                            with self._lock:
                                if generation != self._generation:
                                    return
                            capture = self._opener(
                                source_to_open, backend, self._width, self._height, self._fps,
                            )

                if capture is not None and capture.isOpened():
                    with self._lock:
                        if generation == self._generation:
                            self._capture = capture
                            self._device = device
                            self._open_device = source_to_open
                            self._backend = backend
                            capture = None  # Ownership moved into the slot.
            finally:
                try:
                    if capture is not None:
                        capture.release()
                finally:
                    self._finish_request(generation)

    def prime_async(
        self,
        *,
        device: int,
        open_device: int | str | None = None,
        backend: int,
    ) -> None:
        """Reserve an opening before scheduling its background thread."""
        generation = self._reserve_prime()
        try:
            threading.Thread(
                target=self._prime_reserved,
                kwargs={
                    "generation": generation,
                    "device": device,
                    "open_device": open_device,
                    "backend": backend,
                },
                daemon=True,
            ).start()
        except Exception:
            self._finish_request(generation)
            raise

    def take(self, *, device: int) -> tuple[Any | None, int | None]:
        """Finish any current open and cancel queued primes before handoff."""
        with self._operation_lock:
            with self._lock:
                self._generation += 1
                self._ready.set()
                if self._device != device or self._capture is None:
                    return None, None
                backend = self._backend
                capture = self._detach_locked()

            if capture.isOpened():
                return capture, backend

            capture.release()
            return None, None

    def return_capture(
        self,
        *,
        capture: Any,
        device: int,
        open_device: int | str | None = None,
        backend: int | None,
    ) -> None:
        """Return a capture handle to the persistent pool."""
        self.prime(
            device=device,
            open_device=open_device,
            backend=int(backend or 0),
            capture=capture,
        )

    def read(self) -> tuple[bool, Any | None]:
        """Read one frame from the persistent capture if present."""
        with self._lock:
            capture = self._capture
            if capture is None or not capture.isOpened():
                return False, None
            return capture.read()

    def release(self) -> None:
        """Cancel pending primes and wait until their handles are released."""
        with self._lock:
            self._generation += 1
            self._ready.clear()
        # Do not take the registry's open_lock: an in-flight prime may already
        # be waiting for it. Its operation lock also covers releasing stale opens.
        with self._operation_lock:
            try:
                with self._lock:
                    # Also cancel requests queued while the previous opener
                    # was draining. None may reopen after this handoff.
                    self._generation += 1
                    generation = self._generation
                    capture = self._detach_locked()
                if capture is not None:
                    capture.release()
            finally:
                self._finish_request(generation)
