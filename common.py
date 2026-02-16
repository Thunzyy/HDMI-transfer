# Common configuration for HDMI Exfiltration
import struct

# Resolution settings (Must match the display/capture settings)
WIDTH = 1920
HEIGHT = 1080

# Block size in pixels.
# Larger blocks = lower speed but higher resistance to compression/noise.
# 8x8 is a good starting point for 1080p.
BLOCK_SIZE = 8

# Protocol magic numbers
SEQ_MAGIC = 0xDA7A        # Sequential protocol identifier
FOUNTAIN_MAGIC = 0xF0C0   # Fountain protocol identifier

# Frame types (sequential protocol only)
FRAME_TYPE_IDLE  = 0x00
FRAME_TYPE_START = 0x01
FRAME_TYPE_DATA  = 0x02
FRAME_TYPE_END   = 0x03

# Sequential header format: magic(2) + type(1) + index(4) + total(4) + data_len(2) = 13 pre-CRC
SEQ_HEADER_FMT = '>HBIIH'
SEQ_HEADER_PRE_CRC = struct.calcsize(SEQ_HEADER_FMT)  # 13
SEQ_CRC_SIZE = 4

# Header size in bytes (pre-CRC header + CRC32)
HEADER_SIZE = SEQ_HEADER_PRE_CRC + SEQ_CRC_SIZE  # 17

# Calculate capacity per frame
COLS = WIDTH // BLOCK_SIZE
ROWS = HEIGHT // BLOCK_SIZE
BLOCKS_PER_FRAME = COLS * ROWS

# Capacity calculation for ROBUST MODE (3 bits per block - 1 bit per channel)
# We use 0 or 255 values to be robust against noise.
# Each block = 3 bits.
BITS_PER_FRAME = BLOCKS_PER_FRAME * 3
BYTES_PER_FRAME = (BITS_PER_FRAME // 8) - HEADER_SIZE
