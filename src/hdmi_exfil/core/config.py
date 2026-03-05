"""Central configuration loaded from constants.json.

All encoding parameters are defined in constants.json (single source of truth).
Derived values (COLS, ROWS, BYTES_PER_FRAME, etc.) are computed here.

Also provides ``ResolutionProfile`` -- a frozen dataclass capturing resolution,
block-size, and target-fps for a named preset -- and a ``PROFILES`` registry
of three built-in presets (speed, balanced, quality).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from importlib.resources import files


# ---------------------------------------------------------------------------
# Load constants from JSON (single source of truth)
# ---------------------------------------------------------------------------

_constants_path = files("hdmi_exfil.core").joinpath("constants.json")
_constants = json.loads(_constants_path.read_text(encoding="utf-8"))

# Core encoding parameters (from constants.json)
WIDTH: int = _constants["width"]
HEIGHT: int = _constants["height"]
BLOCK_SIZE: int = _constants["block_size"]
SEQ_MAGIC: int = _constants["seq_magic"]
FOUNTAIN_MAGIC: int = _constants["fountain_magic"]
THRESHOLD: int = _constants["threshold"]

# ---------------------------------------------------------------------------
# Protocol-specific constants (not in JSON -- defined directly)
# ---------------------------------------------------------------------------

# Frame types (sequential protocol only)
FRAME_TYPE_IDLE: int = 0x00
FRAME_TYPE_START: int = 0x01
FRAME_TYPE_DATA: int = 0x02
FRAME_TYPE_END: int = 0x03

# Sequential header format: magic(2) + type(1) + index(4) + total(4) + data_len(2)
SEQ_HEADER_FMT: str = ">HBIIH"
SEQ_HEADER_PRE_CRC: int = struct.calcsize(SEQ_HEADER_FMT)  # 13
SEQ_CRC_SIZE: int = 4

# Header size in bytes (pre-CRC header + CRC32)
HEADER_SIZE: int = SEQ_HEADER_PRE_CRC + SEQ_CRC_SIZE  # 17

# ---------------------------------------------------------------------------
# Resolution profiles
# ---------------------------------------------------------------------------

# Fountain header size duplicated here to avoid circular import with
# fountain.py. Value (v2): magic(2) + seed(4) + K(2) + max_droplets(4)
# + crc32(4) = 16 bytes.
_FOUNT_HEADER_SIZE: int = 16


@dataclass(frozen=True)
class ResolutionProfile:
    """Immutable bundle of resolution / encoding parameters for a named preset.

    Spatial dimensions (cols, rows, blocks, bits, bytes-per-frame) are derived
    from *width*, *height*, and *block_size*.  ``target_fps`` is advisory --
    the display layer uses it to pace frame output.
    """

    name: str
    width: int
    height: int
    block_size: int
    target_fps: int
    bits_per_channel: int = 1

    # -- derived properties --------------------------------------------------

    @property
    def cols(self) -> int:
        """Number of block columns in the encoding grid."""
        return self.width // self.block_size

    @property
    def rows(self) -> int:
        """Number of block rows in the encoding grid."""
        return self.height // self.block_size

    @property
    def blocks_per_frame(self) -> int:
        """Total blocks in one frame (cols * rows)."""
        return self.cols * self.rows

    @property
    def bits_per_frame(self) -> int:
        """Total encoded bits per frame (3 channels * bpc bits per block)."""
        return self.blocks_per_frame * 3 * self.bits_per_channel

    @property
    def seq_bytes_per_frame(self) -> int:
        """Payload capacity for the sequential protocol (after header)."""
        return (self.bits_per_frame // 8) - HEADER_SIZE

    @property
    def fount_header_size(self) -> int:
        """Fountain header size in bytes (duplicated to avoid circular import)."""
        return _FOUNT_HEADER_SIZE

    @property
    def fount_bytes_per_frame(self) -> int:
        """Payload capacity for the fountain protocol (after header)."""
        return (self.bits_per_frame // 8) - self.fount_header_size


PROFILES: dict[str, ResolutionProfile] = {
    "speed": ResolutionProfile("speed", 1920, 1080, 8, 240),
    "balanced": ResolutionProfile("balanced", 1920, 1080, 8, 60),
    "quality": ResolutionProfile("quality", 3840, 2160, 8, 30),
}

DEFAULT_PROFILE: ResolutionProfile = PROFILES["speed"]


# ---------------------------------------------------------------------------
# Derived capacity values
# ---------------------------------------------------------------------------

COLS: int = WIDTH // BLOCK_SIZE
ROWS: int = HEIGHT // BLOCK_SIZE
BLOCKS_PER_FRAME: int = COLS * ROWS

# Robust mode: 3 bits per block (1 bit per channel, 0 or 255)
BITS_PER_FRAME: int = BLOCKS_PER_FRAME * 3
BYTES_PER_FRAME: int = (BITS_PER_FRAME // 8) - HEADER_SIZE
