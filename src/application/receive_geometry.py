"""Shared frame geometry handling for receiver adapters."""

from __future__ import annotations

import cv2
import numpy as np

from hdmi_exfil.core.capture.sampler import sample_frame
from hdmi_exfil.core.config import ResolutionProfile


def ensure_frame_size(frame, profile: ResolutionProfile):
    """Resize frames to the expected profile size while preserving block edges."""
    if (
        frame.shape[0] != profile.height
        or frame.shape[1] != profile.width
    ):
        return cv2.resize(
            frame,
            (profile.width, profile.height),
            interpolation=cv2.INTER_NEAREST,
        )
    return frame


def sample_grid(
    frame,
    profile: ResolutionProfile,
    sampling: tuple[int, int, float, float],
):
    """Sample a grid using explicit offset and scale geometry."""
    offset_x, offset_y, scale_x, scale_y = sampling
    return sample_frame(
        frame,
        profile.rows,
        profile.cols,
        profile.block_size,
        offset_x=offset_x,
        offset_y=offset_y,
        scale_x=scale_x,
        scale_y=scale_y,
    )


def build_geometry_candidates(
    profile: ResolutionProfile,
) -> list[tuple[int, int, float, float]]:
    """Return common browser/content-box geometry fallbacks."""
    width = int(profile.width)
    height = int(profile.height)
    candidates: list[tuple[int, int, float, float]] = [(0, 0, 1.0, 1.0)]
    seen = {candidates[0]}

    def push(vw: int, vh: int, align_x: str, align_y: str) -> None:
        if vw <= 0 or vh <= 0:
            return
        sx = float(vw / width)
        sy = float(vh / height)
        ox = 0 if align_x == "left" else max(0, (width - vw) // 2)
        oy = 0 if align_y == "top" else max(0, (height - vh) // 2)
        key = (int(ox), int(oy), round(sx, 6), round(sy, 6))
        if key in seen:
            return
        seen.add(key)
        candidates.append((int(ox), int(oy), sx, sy))

    h_candidates = [
        height - d
        for d in (
            8, 16, 24, 32, 40, 48, 52, 56, 64, 80, 96, 120, 128, 144, 147,
            160, 180, 200,
        )
    ]
    w_candidates = [
        width - d
        for d in (8, 16, 24, 32, 40, 64, 80, 96, 120, 160, 192)
    ]

    for vh in h_candidates:
        push(width, vh, "left", "top")
        push(width, vh, "left", "center")

    for vw in w_candidates:
        push(vw, height, "left", "top")
        push(vw, height, "center", "top")

    for vw in (width - 16, width - 24, width - 32, width - 64, width - 96):
        for vh in (
            height - 48,
            height - 52,
            height - 56,
            height - 64,
            height - 96,
            height - 120,
            height - 147,
        ):
            push(vw, vh, "center", "center")

    for vw, vh in ((1904, 933), (1904, 989), (1904, 1028), (1920, 1028), (1920, 1032)):
        push(vw, vh, "center", "center")

    return candidates


def estimate_sampling_from_frame(
    frame,
    profile: ResolutionProfile,
) -> tuple[int, int, float, float] | None:
    """Estimate active content area from frame variance."""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        row_std = gray.std(axis=1)
        col_std = gray.std(axis=0)

        row_thr = max(6.0, float(np.percentile(row_std, 70) * 0.5))
        col_thr = max(6.0, float(np.percentile(col_std, 70) * 0.5))

        rows = np.where(row_std >= row_thr)[0]
        cols = np.where(col_std >= col_thr)[0]
        if rows.size == 0 or cols.size == 0:
            return None

        top = int(rows[0])
        bottom = int(rows[-1])
        left = int(cols[0])
        right = int(cols[-1])
        vh = max(1, bottom - top + 1)
        vw = max(1, right - left + 1)

        if vh < int(profile.height * 0.55) or vw < int(profile.width * 0.55):
            return None

        sx = float(vw / profile.width)
        sy = float(vh / profile.height)
        return (left, top, sx, sy)
    except Exception:
        return None


def decode_with_sampling_fallbacks(
    frame,
    profile: ResolutionProfile,
    decode_frame,
    sampling: tuple[int, int, float, float],
    geometry_candidates: list[tuple[int, int, float, float]],
    geometry_cursor: int,
    *,
    extra_candidates: int = 5,
):
    """Try current sampling first, then dynamic/browser-style geometry fallbacks."""
    batch: list[tuple[int, int, float, float]] = []
    seen: set[tuple[int, int, float, float]] = set()

    def add(candidate: tuple[int, int, float, float]) -> None:
        key = (
            int(candidate[0]),
            int(candidate[1]),
            round(float(candidate[2]), 6),
            round(float(candidate[3]), 6),
        )
        if key in seen:
            return
        seen.add(key)
        batch.append(candidate)

    add(sampling)
    add((0, 0, 1.0, 1.0))

    dynamic_sampling = estimate_sampling_from_frame(frame, profile)
    if dynamic_sampling is not None:
        add(dynamic_sampling)

    if len(geometry_candidates) > 1:
        for _ in range(extra_candidates):
            geometry_cursor = (geometry_cursor + 1) % len(geometry_candidates)
            if geometry_cursor == 0:
                geometry_cursor = 1
            add(geometry_candidates[geometry_cursor])

    for candidate in batch:
        sampled = sample_grid(frame, profile, candidate)
        result = decode_frame(sampled)
        if getattr(result, "is_valid", False):
            return result, geometry_cursor, candidate

    return None, geometry_cursor, None
