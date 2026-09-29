"""Application-layer events shared by sender and receiver workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


FrameKind = Literal["start", "data", "end", "droplet"]
ReceiveEventKind = Literal["status", "progress", "complete"]


@dataclass(frozen=True)
class FramePacket:
    """Encoded frame plus the workflow metadata needed by the UI layer."""

    kind: FrameKind
    frame: np.ndarray
    frame_index: int
    total_frames: int
    seed: int | None = None


@dataclass(frozen=True)
class ReceiveEvent:
    """State transition emitted by the shared receive session."""

    kind: ReceiveEventKind
    data: dict[str, object]
