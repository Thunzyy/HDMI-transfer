"""Central configuration loaded from constants.json.

All encoding parameters are defined in constants.json (single source of truth).
Derived values (COLS, ROWS, BYTES_PER_FRAME, etc.) are computed here.
"""

import json
import struct
from importlib.resources import files


# ---------------------------------------------------------------------------
# Load constants from JSON (single source of truth)
# ---------------------------------------------------------------------------

_constants_path = files("hdmi_exfil").joinpath("constants.json")
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
# Derived capacity values
# ---------------------------------------------------------------------------

COLS: int = WIDTH // BLOCK_SIZE
ROWS: int = HEIGHT // BLOCK_SIZE
BLOCKS_PER_FRAME: int = COLS * ROWS

# Robust mode: 3 bits per block (1 bit per channel, 0 or 255)
BITS_PER_FRAME: int = BLOCKS_PER_FRAME * 3
BYTES_PER_FRAME: int = (BITS_PER_FRAME // 8) - HEADER_SIZE
