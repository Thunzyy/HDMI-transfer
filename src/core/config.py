"""Protocol configuration derived from the shared manifest."""

from __future__ import annotations

from hdmi_transfer.domain.models import ResolutionProfile
from hdmi_transfer.domain.protocol_manifest import get_protocol_manifest

_manifest = get_protocol_manifest()

WIDTH: int = _manifest.width
HEIGHT: int = _manifest.height
BLOCK_SIZE: int = _manifest.block_size
SEQ_MAGIC: int = _manifest.sequential.magic
FOUNTAIN_MAGIC: int = _manifest.fountain.magic
THRESHOLD: int = _manifest.threshold

# ---------------------------------------------------------------------------
# Protocol-specific constants (not in JSON -- defined directly)
# ---------------------------------------------------------------------------

# Frame types (sequential protocol only)
FRAME_TYPE_IDLE: int = 0x00
FRAME_TYPE_START: int = 0x01
FRAME_TYPE_DATA: int = 0x02
FRAME_TYPE_END: int = 0x03

SEQ_HEADER_FMT: str = _manifest.sequential.header_format
SEQ_HEADER_PRE_CRC: int = _manifest.sequential.header_pre_crc
SEQ_CRC_SIZE: int = _manifest.sequential.crc_size
HEADER_SIZE: int = _manifest.sequential.header_size

PROFILES: dict[str, ResolutionProfile] = _manifest.profiles

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
