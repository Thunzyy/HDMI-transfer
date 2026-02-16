"""Cross-platform VideoCapture wrapper.

Auto-detects the preferred OpenCV backend for the current platform
(V4L2 on Linux, DSHOW on Windows, AVFoundation on macOS) and falls back
to ``CAP_ANY`` when the preferred backend fails to open the source.

Usage::

    with CaptureSource(0) as cap:
        ret, frame = cap.read()
"""

from __future__ import annotations

import sys

import cv2


def get_capture_backend() -> int:
    """Return the preferred ``cv2.VideoCapture`` backend for this platform.

    Returns
    -------
    int
        ``cv2.CAP_V4L2`` on Linux, ``cv2.CAP_DSHOW`` on Windows,
        ``cv2.CAP_AVFOUNDATION`` on macOS, ``cv2.CAP_ANY`` otherwise.
    """
    platform = sys.platform
    if platform.startswith("linux"):
        return cv2.CAP_V4L2
    if platform == "win32":
        return cv2.CAP_DSHOW
    if platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


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
        source: int | str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 60,
    ) -> None:
        backend = get_capture_backend()
        self._cap = cv2.VideoCapture(source, backend)

        # Fallback to CAP_ANY if the preferred backend fails
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(source, cv2.CAP_ANY)

        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open video source {source}")

        # Request desired capture properties
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)

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
