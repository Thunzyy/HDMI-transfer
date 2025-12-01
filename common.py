# Common configuration for HDMI Exfiltration

# Resolution settings (Must match the display/capture settings)
WIDTH = 1920
HEIGHT = 1080
# We use 0 or 255 values to be robust against noise.
# Each block = 3 bits.
BITS_PER_FRAME = BLOCKS_PER_FRAME * 3
BYTES_PER_FRAME = (BITS_PER_FRAME // 8) - HEADER_SIZE
