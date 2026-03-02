"""Fullscreen frame display renderers.

Provides two renderer implementations:

* :class:`FrameRenderer` -- OpenCV-based (``cv2.imshow``), simple and portable.
  Capped at ~80 fps due to ``cv2.waitKey`` overhead.

* :class:`PygameRenderer` -- SDL2-based (``pygame-ce``), vsync-locked for
  native refresh rate rendering (120/144/240 fps).  Preferred for
  high-throughput HDMI exfiltration.

Usage::

    with FrameRenderer(x_offset=1920) as renderer:
        renderer.show(frame)

    with PygameRenderer(x_offset=1920) as renderer:
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


class PygameRenderer:
    """SDL2 fullscreen renderer via pygame-ce for vsync-locked display.

    Replaces FrameRenderer for sender-side display when high FPS (>80)
    is needed. Uses pygame.surfarray.blit_array for efficient numpy->surface
    transfer and pygame.display.flip() for vsync-locked presentation.

    Parameters
    ----------
    width:
        Display width in pixels (default 1920).
    height:
        Display height in pixels (default 1080).
    x_offset:
        Horizontal position for multi-monitor placement.
    y_offset:
        Vertical position for multi-monitor placement.
    """

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        x_offset: int = 0,
        y_offset: int = 0,
    ) -> None:
        import os

        import pygame  # lazy import (only needed when PygameRenderer is used)

        self._pygame = pygame

        # Position window via SDL environment variable BEFORE init
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{x_offset},{y_offset}"

        pygame.init()

        # Try vsync first, fall back to no vsync
        try:
            self._screen = pygame.display.set_mode(
                (width, height),
                pygame.FULLSCREEN | pygame.NOFRAME,
                vsync=1,
            )
        except pygame.error:
            self._screen = pygame.display.set_mode(
                (width, height),
                pygame.FULLSCREEN | pygame.NOFRAME,
            )

        self._width = width
        self._height = height
        self._clock = pygame.time.Clock()
        # Pre-allocate surface to avoid per-frame allocation
        self._surface = pygame.Surface((width, height))

    # -- Core operations -----------------------------------------------------

    def show(self, frame: np.ndarray, delay_ms: int = 1) -> int:
        """Display a (H, W, 3) uint8 BGR numpy array.

        Handles BGR->RGB conversion and (H,W,3)->(W,H,3) transpose
        for pygame surfarray compatibility.

        Parameters
        ----------
        frame:
            BGR image as numpy.ndarray with shape (H, W, 3).
        delay_ms:
            Ignored (vsync handles timing). Kept for API compatibility
            with FrameRenderer.

        Returns
        -------
        int
            Key code if a key was pressed, or 255 if no key event.
            ESC (27) signals quit. API compatible with FrameRenderer.
        """
        pg = self._pygame

        # BGR -> RGB (cv2 uses BGR, pygame uses RGB)
        rgb_frame = frame[:, :, ::-1]
        # (H, W, 3) -> (W, H, 3) for pygame surfarray
        transposed = np.ascontiguousarray(rgb_frame.transpose(1, 0, 2))

        pg.surfarray.blit_array(self._surface, transposed)
        self._screen.blit(self._surface, (0, 0))
        pg.display.flip()  # vsync-locked if enabled

        # Process events (must pump to avoid OS "not responding")
        key_code = 255  # match FrameRenderer convention (no key)
        for event in pg.event.get():
            if event.type == pg.QUIT:
                key_code = 27  # ESC
            elif event.type == pg.KEYDOWN:
                if event.key == pg.K_ESCAPE:
                    key_code = 27
                else:
                    key_code = event.key & 0xFF

        return key_code

    def destroy(self) -> None:
        """Shut down pygame display."""
        self._pygame.quit()

    # -- Context manager -----------------------------------------------------

    def __enter__(self) -> PygameRenderer:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.destroy()
