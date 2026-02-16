"""Fullscreen OpenCV frame display.

Creates a named window, moves it to the specified screen offset, and
switches to fullscreen mode.  The :class:`FrameRenderer` wraps the
repetitive ``cv2.namedWindow`` / ``cv2.imshow`` / ``cv2.waitKey`` /
``cv2.destroyAllWindows`` lifecycle.

Usage::

    with FrameRenderer(x_offset=1920) as renderer:
        renderer.show(frame)
"""

from __future__ import annotations

import cv2
import numpy as np


class FrameRenderer:
    """Fullscreen OpenCV window for displaying encoded frames.

    Parameters
    ----------
    window_name:
        OpenCV window title.
    x_offset:
        Horizontal pixel offset (use for multi-monitor placement).
    y_offset:
        Vertical pixel offset.
    """

    def __init__(
        self,
        window_name: str = "HDMI Exfil",
        x_offset: int = 0,
        y_offset: int = 0,
    ) -> None:
        self._window_name = window_name
        cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
        cv2.moveWindow(self._window_name, x_offset, y_offset)
        cv2.setWindowProperty(
            self._window_name,
            cv2.WND_PROP_FULLSCREEN,
            cv2.WINDOW_FULLSCREEN,
        )

    # -- Core operations -----------------------------------------------------

    def show(self, frame: np.ndarray, delay_ms: int = 1) -> int:
        """Display *frame* and wait for *delay_ms* milliseconds.

        Parameters
        ----------
        frame:
            BGR image (``numpy.ndarray``, shape ``(H, W, 3)``).
        delay_ms:
            Milliseconds to wait (``cv2.waitKey`` argument).

        Returns
        -------
        int
            Key code returned by ``cv2.waitKey`` (masked to 8 bits).
        """
        cv2.imshow(self._window_name, frame)
        return cv2.waitKey(delay_ms) & 0xFF

    def destroy(self) -> None:
        """Close all OpenCV windows."""
        cv2.destroyAllWindows()

    # -- Context manager -----------------------------------------------------

    def __enter__(self) -> FrameRenderer:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.destroy()
