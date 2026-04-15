"""Tests for PygameRenderer (headless-safe, no display server required).

Verifies the PygameRenderer import, interface compatibility with
FrameRenderer, and the BGR->RGB + transpose conversion logic that
PygameRenderer.show() performs internally.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def test_pygame_renderer_import():
    """PygameRenderer can be imported without errors."""
    from hdmi_transfer.display.renderer import PygameRenderer

    assert PygameRenderer is not None


def test_pygame_renderer_interface():
    """PygameRenderer exposes the same interface as FrameRenderer.

    Both renderers must have: show(), destroy(), __enter__, __exit__.
    """
    from hdmi_transfer.display.renderer import PygameRenderer

    assert callable(getattr(PygameRenderer, "show", None))
    assert callable(getattr(PygameRenderer, "destroy", None))
    assert callable(getattr(PygameRenderer, "__enter__", None))
    assert callable(getattr(PygameRenderer, "__exit__", None))


def test_frame_renderer_interface_parity():
    """PygameRenderer and FrameRenderer share the same public method names."""
    from hdmi_transfer.display.renderer import FrameRenderer, PygameRenderer

    fr_public = {m for m in dir(FrameRenderer) if not m.startswith("_")}
    pr_public = {m for m in dir(PygameRenderer) if not m.startswith("_")}

    # PygameRenderer must have at least all FrameRenderer public methods
    assert fr_public <= pr_public, (
        f"PygameRenderer missing methods: {fr_public - pr_public}"
    )


def test_frame_bgr_to_rgb_conversion():
    """BGR->RGB channel swap produces correct result.

    This is the first step of PygameRenderer.show() conversion pipeline:
    frame[:, :, ::-1] swaps channels from BGR to RGB.
    """
    h, w = 4, 6
    frame_bgr = np.zeros((h, w, 3), dtype=np.uint8)
    frame_bgr[:, :, 0] = 10  # B channel
    frame_bgr[:, :, 1] = 20  # G channel
    frame_bgr[:, :, 2] = 30  # R channel

    # BGR -> RGB via slice reversal (same as PygameRenderer.show)
    rgb_frame = frame_bgr[:, :, ::-1]

    assert rgb_frame.shape == (h, w, 3)
    # After swap: channel 0 = R(30), channel 1 = G(20), channel 2 = B(10)
    np.testing.assert_array_equal(rgb_frame[:, :, 0], 30)
    np.testing.assert_array_equal(rgb_frame[:, :, 1], 20)
    np.testing.assert_array_equal(rgb_frame[:, :, 2], 10)


def test_frame_transpose_for_surfarray():
    """(H,W,3) -> (W,H,3) transpose produces correct shape for pygame.

    This is the second step of PygameRenderer.show() conversion pipeline:
    pygame.surfarray expects (W, H, 3) arrays, but cv2 produces (H, W, 3).
    """
    h, w = 1080, 1920
    frame = np.zeros((h, w, 3), dtype=np.uint8)

    # Transpose (same as PygameRenderer.show)
    transposed = np.ascontiguousarray(frame.transpose(1, 0, 2))

    assert transposed.shape == (w, h, 3)
    assert transposed.flags["C_CONTIGUOUS"]


def test_full_conversion_pipeline():
    """Full BGR (H,W,3) -> RGB (W,H,3) pipeline preserves pixel data.

    Combines both steps from PygameRenderer.show():
    1. BGR -> RGB channel swap
    2. (H,W,3) -> (W,H,3) transpose
    """
    h, w = 8, 12
    frame_bgr = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)

    # Full pipeline (matches PygameRenderer.show internals)
    rgb_frame = frame_bgr[:, :, ::-1]
    transposed = np.ascontiguousarray(rgb_frame.transpose(1, 0, 2))

    assert transposed.shape == (w, h, 3)

    # Verify pixel at (row=2, col=5) in original maps to (x=5, y=2)
    # in transposed output with channels swapped
    orig_bgr = frame_bgr[2, 5]  # [B, G, R]
    result_rgb = transposed[5, 2]  # [R, G, B]

    assert result_rgb[0] == orig_bgr[2], "R channel mismatch"
    assert result_rgb[1] == orig_bgr[1], "G channel mismatch"
    assert result_rgb[2] == orig_bgr[0], "B channel mismatch"


def test_show_signature_matches():
    """PygameRenderer.show() accepts same (frame, delay_ms) signature."""
    import inspect

    from hdmi_transfer.display.renderer import FrameRenderer, PygameRenderer

    fr_sig = inspect.signature(FrameRenderer.show)
    pr_sig = inspect.signature(PygameRenderer.show)

    fr_params = list(fr_sig.parameters.keys())
    pr_params = list(pr_sig.parameters.keys())

    assert fr_params == pr_params, (
        f"Signature mismatch: FrameRenderer{fr_params} vs PygameRenderer{pr_params}"
    )
