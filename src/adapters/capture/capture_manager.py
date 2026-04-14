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
        self._ready = threading.Event()
        self._ready.set()
        self._capture: Any | None = None
        self._device: int | None = None
        self._open_device: int | None = None
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
        self._ready.clear()
        previous: Any | None = None
        source_to_open = open_device if open_device is not None else device

        with self._lock:
            previous = self._capture
            self._capture = None
            self._device = None
            self._open_device = None
            self._backend = None

        if previous is not None:
            previous.release()

        try:
            if capture is None:
                if self._opener is None:
                    raise RuntimeError(
                        "CaptureManager requires an opener when capture is not provided",
                    )
                if self._open_lock is None:
                    capture = self._opener(
                        source_to_open,
                        backend,
                        self._width,
                        self._height,
                        self._fps,
                    )
                else:
                    with self._open_lock:
                        capture = self._opener(
                            source_to_open,
                            backend,
                            self._width,
                            self._height,
                            self._fps,
                        )

            if capture is not None and capture.isOpened():
                with self._lock:
                    self._capture = capture
                    self._device = device
                    self._open_device = source_to_open
                    self._backend = backend
            elif capture is not None:
                capture.release()
        finally:
            self._ready.set()

    def prime_async(
        self,
        *,
        device: int,
        open_device: int | str | None = None,
        backend: int,
    ) -> None:
        """Open a persistent capture in a background thread."""
        threading.Thread(
            target=self.prime,
            kwargs={
                "device": device,
                "open_device": open_device,
                "backend": backend,
            },
            daemon=True,
        ).start()

    def take(self, *, device: int) -> tuple[Any | None, int | None]:
        """Take ownership of the matching persistent capture if available."""
        with self._lock:
            if self._device != device or self._capture is None:
                return None, None
            capture = self._capture
            backend = self._backend
            self._capture = None
            self._device = None
            self._open_device = None
            self._backend = None

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
        """Release any persistent capture and clear the slot."""
        self._ready.set()
        with self._lock:
            capture = self._capture
            self._capture = None
            self._device = None
            self._open_device = None
            self._backend = None
        if capture is not None:
            capture.release()
