# Common configuration for HDMI Exfiltration

# Resolution settings (Must match the display/capture settings)
WIDTH = 1920
HEIGHT = 1080

# Block size in pixels. 
# Larger blocks = lower speed but higher resistance to compression/noise.
# 8x8 is a good starting point for 1080p.
BLOCK_SIZE = 8

# Header size in bytes (Frame Index: 4 bytes, Data Length: 4 bytes)
HEADER_SIZE = 8

# Calculate capacity per frame
COLS = WIDTH // BLOCK_SIZE
ROWS = HEIGHT // BLOCK_SIZE
BLOCKS_PER_FRAME = COLS * ROWS
# Capacity calculation for ROBUST MODE (3 bits per block - 1 bit per channel)
# We use 0 or 255 values to be robust against noise.
# Each block = 3 bits.
BITS_PER_FRAME = BLOCKS_PER_FRAME * 3
BYTES_PER_FRAME = (BITS_PER_FRAME // 8) - HEADER_SIZE
