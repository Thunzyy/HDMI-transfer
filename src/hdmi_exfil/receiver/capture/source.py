"""Cross-platform VideoCapture wrapper.

Auto-detects the preferred OpenCV backend for the current platform
(V4L2 on Linux, DSHOW on Windows, AVFoundation on macOS) and falls back
through MSMF then ``CAP_ANY`` when the preferred backend fails.

A backend is considered *failed* if it cannot open the source **or** if the
negotiated resolution is far below the requested resolution (e.g. the
device reports 640x480 when 1920x1080 was requested).  On Windows the
DSHOW driver for some capture cards (notably Elgato) sometimes opens
successfully but returns black frames at a default resolution — the
validation step catches this and tries the next backend.

Usage::

    with CaptureSource(0) as cap:
        ret, frame = cap.read()
"""

from __future__ import annotations

import sys

import cv2


def _get_backends() -> list[int]:
    """Return an ordered list of backends to try for the current platform.

    On Windows, MSMF is preferred over DSHOW because some capture cards
    (e.g. Elgato 4K X) only deliver valid frames through MSMF while the
    DSHOW driver opens successfully but returns all-zero frames.
    """
    if sys.platform.startswith("linux"):
        return [cv2.CAP_V4L2, cv2.CAP_ANY]
    if sys.platform == "win32":
        return [cv2.CAP_MSMF, cv2.CAP_DSHOW, cv2.CAP_ANY]
    if sys.platform == "darwin":
        return [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
    return [cv2.CAP_ANY]


def _try_open(
    source: int | str,
    backend: int,
    width: int,
    height: int,
    fps: int,
) -> cv2.VideoCapture | None:
    """Try to open *source* with *backend* and validate the result.

    Returns the open ``VideoCapture`` if the device negotiated a
    resolution at least half the requested width/height **and** delivers
    at least one non-empty frame, otherwise releases and returns ``None``.

    Some DSHOW drivers claim high resolution after ``set()`` but deliver
    all-zero frames.  Reading a test frame catches this.
    """
    import numpy as np

    cap = cv2.VideoCapture(source, backend)
    if not cap.isOpened():
        return None

    # Record pre-set resolution to detect lying drivers
    pre_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    pre_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Reject if the device fell back to a tiny default resolution
    if actual_w < width // 2 or actual_h < height // 2:
        cap.release()
        return None

    # DSHOW-specific: if resolution jumped from a low default after set(),
    # the driver may be lying (claims 1920x1080 but delivers all-zero frames).
    # Read several test frames to catch this.
    if backend == cv2.CAP_DSHOW and pre_w <= 640 and pre_h <= 480 and actual_w > 640:
        all_zero = True
        for _ in range(8):
            ret, frame = cap.read()
            if ret and isinstance(frame, np.ndarray) and frame.max() > 0:
                all_zero = False
                break
        if all_zero:
            cap.release()
            return None

    return cap


def _try_open_validated(
    source: int | str,
    backend: int,
    width: int,
    height: int,
    fps: int,
) -> cv2.VideoCapture | None:
    """Open and validate a device can actually read frames.

    Like ``_try_open`` but additionally reads a test frame to confirm
    the device is fully functional.  Used by device detection.
    """
    import numpy as np

    cap = _try_open(source, backend, width, height, fps)
    if cap is None:
        return None

    # Quick validation: try to read one frame
    ret, frame = cap.read()
    if not ret or not isinstance(frame, np.ndarray):
        cap.release()
        return None

    return cap


class CaptureSource:
    """Cross-platform video capture with automatic backend selection.

    Parameters
    ----------
    source:
        Camera index (``int``) or video file path (``str``).
    width:
        Requested frame width in pixels.
    height:
        Requested frame height in pixels.
    fps:
        Requested capture frame rate.
    """

    def __init__(
        self,
        source: int | str = 0,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
        backend: int | None = None,
        _precap: cv2.VideoCapture | None = None,
    ) -> None:
        self._cap: cv2.VideoCapture | None = None

        if _precap is not None and _precap.isOpened():
            # Use pre-warmed capture — no probing needed
            self._cap = _precap
        elif backend is not None:
            cap = _try_open(source, backend, width, height, fps)
            if cap is not None:
                self._cap = cap

        if self._cap is None:
            for b in _get_backends():
                cap = _try_open(source, b, width, height, fps)
                if cap is not None:
                    self._cap = cap
                    break

        if self._cap is None:
            raise RuntimeError(f"Could not open video source {source}")

        # Read back the actual values the device negotiated
        self._actual_width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._actual_height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

    # -- Properties ----------------------------------------------------------

    @property
    def actual_width(self) -> int:
        """Actual frame width reported by the capture device."""
        return self._actual_width

    @property
    def actual_height(self) -> int:
        """Actual frame height reported by the capture device."""
        return self._actual_height

    @property
    def actual_fps(self) -> float:
        """Actual FPS reported by the capture device."""
        return self._actual_fps

    # -- Core operations -----------------------------------------------------

    def read(self) -> tuple[bool, object]:
        """Read a single frame.

        Returns
        -------
        tuple[bool, numpy.ndarray | None]
            ``(success, frame)`` -- mirrors ``cv2.VideoCapture.read()``.
        """
        return self._cap.read()

    def release(self) -> None:
        """Release the underlying VideoCapture resource."""
        self._cap.release()

    # -- Context manager -----------------------------------------------------

    def __enter__(self) -> CaptureSource:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.release()
