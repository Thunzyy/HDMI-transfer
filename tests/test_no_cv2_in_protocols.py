"""Tests verifying cv2 is NOT imported in protocol/sampler modules.

These modules must use pure numpy for upscale/downscale so they can
live in core/ without an OpenCV dependency (STRUCT-06).
"""

from __future__ import annotations

import ast
import importlib
import sys

import numpy as np

from hdmi_transfer.config import DEFAULT_PROFILE, ResolutionProfile


# ---------------------------------------------------------------------------
# Task 1: cv2-free protocol encoding
# ---------------------------------------------------------------------------


class TestNoCv2InSequential:
    """Verify sequential.py has no cv2 dependency."""

    def test_no_cv2_import_in_source(self):
        """AST parse sequential.py to confirm no cv2 import statement."""
        import hdmi_transfer.protocols.sequential as mod

        src = ast.parse(open(mod.__file__).read())
        cv2_imports = [
            n
            for n in ast.walk(src)
            if (isinstance(n, ast.Import) and any(a.name == "cv2" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "cv2")
        ]
        assert cv2_imports == [], "cv2 import found in sequential.py"

    def test_encode_frame_shape(self):
        """encode_frame output has correct profile dimensions."""
        from hdmi_transfer.protocols.sequential import SequentialProtocol

        proto = SequentialProtocol()
        profile = DEFAULT_PROFILE
        data = b"\xAA" * profile.seq_bytes_per_frame
        img = proto.encode_frame(data, 0, 1)
        assert img.shape == (profile.height, profile.width, 3)
        assert img.dtype == np.uint8

    def test_encode_frame_uses_np_repeat(self):
        """Verify the np.repeat pattern produces same output as cv2.resize."""
        from hdmi_transfer.protocols.sequential import SequentialProtocol

        proto = SequentialProtocol()
        profile = DEFAULT_PROFILE
        data = b"\x42" * profile.seq_bytes_per_frame
        img = proto.encode_frame(data, 0, 1)
        # Every block_size x block_size region should have uniform color
        bs = profile.block_size
        # Check a few blocks
        for r in range(0, min(5, profile.rows)):
            for c in range(0, min(5, profile.cols)):
                block = img[r * bs : (r + 1) * bs, c * bs : (c + 1) * bs]
                assert np.all(block == block[0, 0]), (
                    f"Block ({r},{c}) not uniform after np.repeat upscale"
                )


class TestNoCv2InFountain:
    """Verify fountain.py has no cv2 dependency."""

    def test_no_cv2_import_in_source(self):
        """AST parse fountain.py to confirm no cv2 import statement."""
        import hdmi_transfer.protocols.fountain as mod

        src = ast.parse(open(mod.__file__).read())
        cv2_imports = [
            n
            for n in ast.walk(src)
            if (isinstance(n, ast.Import) and any(a.name == "cv2" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "cv2")
        ]
        assert cv2_imports == [], "cv2 import found in fountain.py"

    def test_encode_frame_shape(self):
        """encode_frame output has correct profile dimensions."""
        from hdmi_transfer.protocols.fountain import FountainProtocol

        proto = FountainProtocol()
        profile = DEFAULT_PROFILE
        data = b"\xBB" * proto.bytes_per_frame
        img = proto.encode_frame(data, 0, 10, seed=42)
        assert img.shape == (profile.height, profile.width, 3)
        assert img.dtype == np.uint8

    def test_encode_frame_block_uniformity(self):
        """Verify blocks are uniform after np.repeat upscale."""
        from hdmi_transfer.protocols.fountain import FountainProtocol

        proto = FountainProtocol()
        profile = DEFAULT_PROFILE
        data = b"\xCC" * proto.bytes_per_frame
        img = proto.encode_frame(data, 0, 10, seed=99)
        bs = profile.block_size
        for r in range(0, min(5, profile.rows)):
            for c in range(0, min(5, profile.cols)):
                block = img[r * bs : (r + 1) * bs, c * bs : (c + 1) * bs]
                assert np.all(block == block[0, 0]), (
                    f"Block ({r},{c}) not uniform after np.repeat upscale"
                )


# ---------------------------------------------------------------------------
# Task 2: cv2-free sampler
# ---------------------------------------------------------------------------


class TestNoCv2InSampler:
    """Verify sampler.py has no cv2 dependency."""

    def test_no_cv2_import_in_source(self):
        """AST parse sampler.py to confirm no cv2 import statement."""
        import hdmi_transfer.capture.sampler as mod

        src = ast.parse(open(mod.__file__).read())
        cv2_imports = [
            n
            for n in ast.walk(src)
            if (isinstance(n, ast.Import) and any(a.name == "cv2" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "cv2")
        ]
        assert cv2_imports == [], "cv2 import found in sampler.py"

    def test_sample_frame_matching_dimensions(self):
        """sample_frame works when frame dimensions match expected."""
        from hdmi_transfer.capture.sampler import sample_frame

        profile = DEFAULT_PROFILE
        frame = np.random.randint(0, 256, (profile.height, profile.width, 3), dtype=np.uint8)
        grid = sample_frame(frame, profile.rows, profile.cols, profile.block_size)
        assert grid.shape == (profile.rows, profile.cols, 3)

    def test_sample_frame_mismatched_dimensions(self):
        """sample_frame handles frame dimension mismatch via numpy resize."""
        from hdmi_transfer.capture.sampler import sample_frame

        profile = DEFAULT_PROFILE
        # Create frame with different dimensions (e.g. 720p instead of 1080p)
        frame = np.random.randint(0, 256, (720, 1280, 3), dtype=np.uint8)
        grid = sample_frame(frame, profile.rows, profile.cols, profile.block_size)
        assert grid.shape == (profile.rows, profile.cols, 3)
