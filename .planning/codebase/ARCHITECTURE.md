# Architecture

**Analysis Date:** 2026-02-16

## Pattern Overview

**Overall:** Point-to-point steganographic data channel over HDMI video signal

**Key Characteristics:**
- Asymmetric pipeline: one sender, one receiver, no network involved
- Data is encoded as color blocks in video frames displayed full-screen on a monitor
- Receiver uses a video capture card to read frames off the HDMI signal
- Two independent encoding schemes: Sequential (sender.py / receiver.py) and Fountain codes (sender.html / receiver_fountain.py)
- Shared configuration constants in `common.py` must be identical on both ends

## Layers

**Shared Configuration:**
- Purpose: Constants defining resolution, block size, frame capacity
- Location: `common.py`
- Contains: WIDTH, HEIGHT, BLOCK_SIZE, HEADER_SIZE, BYTES_PER_FRAME
- Depends on: Nothing
- Used by: All sender and receiver modules

**Sender Layer (Sequential, Python):**
- Purpose: Encode a file into sequential video frames and display them fullscreen
- Location: `sender.py`
- Contains: `get_monitors()`, `create_calibration_frame()`, `encode_frame()`, `main()`
- Depends on: `common.py`, OpenCV, NumPy
- Used by: Operator runs directly via CLI

**Sender Layer (Fountain, HTML/JS):**
- Purpose: Browser-based fountain-coded sender that renders to a canvas element
- Location: `sender.html`
- Contains: PRNG (SplitMix32), `chooseIndices()`, `buildDroplet()`, `renderLoop()`, `drawBits()`
- Depends on: Browser APIs (Canvas, FileReader, requestAnimationFrame)
- Used by: Operator opens in fullscreen browser window

**Receiver Layer (Sequential, Python):**
- Purpose: Capture video from capture card, decode sequential frames, reassemble file
- Location: `receiver.py`
- Contains: `sample_frame()`, `decode_frame()`, `main()`
- Depends on: `common.py`, OpenCV, NumPy
- Used by: Operator runs via CLI on capture machine

**Receiver Layer (Fountain, Python):**
- Purpose: Capture video, decode fountain-coded droplets, reconstruct file via belief propagation
- Location: `receiver_fountain.py`
- Contains: `PRNG`, `FountainDecoder`, `sample_frame()`, `decode_frame_data()`, `main()`
- Depends on: `common.py`, OpenCV, NumPy
- Used by: Operator runs via CLI on capture machine (paired with sender.html)

## Data Flow

**Sequential Mode (sender.py → receiver.py):**

1. File is read into memory. If directory, zipped first.
2. Filename prepended as metadata: `[4 bytes name_len][name_bytes]`
3. File split into chunks of `BYTES_PER_FRAME` bytes
4. Each chunk encoded into a frame: header `[frame_index][total_frames][data_len]` packed big-endian, data bits mapped to 0/255 per RGB channel (3 bits/block), scaled to full resolution via nearest-neighbor
5. Frames displayed sequentially fullscreen via OpenCV window
6. Receiver captures each frame via capture card
7. Frame sampled at block centers: `frame[half_block::BLOCK_SIZE, half_block::BLOCK_SIZE]`
8. Threshold applied (>128 = 1), bits unpacked to bytes
9. Header parsed to extract frame index and data length
10. Chunks stored in dict indexed by frame number
11. On completion, chunks concatenated, metadata header parsed, file written to `received_files/`

**Fountain Mode (sender.html → receiver_fountain.py):**

1. File loaded via FileReader API, wrapped with metadata header
2. File split into K fixed-size chunks (PAYLOAD_SIZE = 4044 bytes each)
3. Each rendered frame is a "droplet": seed incremented monotonically, `chooseIndices(seed, K)` uses SplitMix32 PRNG with a degree distribution (1: 10%, 2: 50%, random up to 20: 40%), selected chunks XOR'd together
4. Droplet frame: `[4 bytes seed][2 bytes K][payload]` rendered as 1-bit per block (black/white), displayed via requestAnimationFrame loop at monitor refresh rate
5. Receiver captures frames, decodes seed and K from header
6. `FountainDecoder.add_droplet()` adds each packet, immediately peels known chunks, propagates resolutions via belief propagation graph
7. Transfer complete when `len(decoder.chunks) == K`
8. File data retrieved from decoder, metadata parsed, written to `received_files/`

**State Management:**
- Sequential: dict `received_chunks = {frame_index: bytes_data}` in receiver main loop
- Fountain: `FountainDecoder` object with `chunks` dict, `droplets` list, and `chunk_to_droplets` adjacency map

## Key Abstractions

**Frame Encoding (Sequential):**
- Purpose: Converts raw bytes into a displayable 1920x1080 image
- Examples: `sender.py:encode_frame()`, `receiver.py:decode_frame()`
- Pattern: Bit packing via NumPy (`np.unpackbits`/`np.packbits`), 3 bits per block (one per RGB channel), values 0 or 255 for noise robustness

**Frame Encoding (Fountain):**
- Purpose: Renders a single fountain droplet as a 1-bit-per-block black/white frame
- Examples: `sender.html:drawBits()`, `receiver_fountain.py:decode_frame_data()`
- Pattern: 1 bit per block (green channel threshold), frame header carries PRNG seed for chunk selection reconstruction

**FountainDecoder:**
- Purpose: Belief-propagation / peeling decoder for Luby Transform fountain codes
- Examples: `receiver_fountain.py:FountainDecoder`
- Pattern: Graph of droplets and unknown chunks; when a droplet resolves to degree-1, the chunk is recovered and propagated to all dependent droplets

**Metadata Header:**
- Purpose: Embed original filename in the data stream for transparent save
- Pattern: `[4 bytes big-endian uint32 name_len][UTF-8 name bytes][file content]` — applied in both sequential and fountain modes

**Block Sampling:**
- Purpose: Robust pixel sampling at expected block center coordinates
- Examples: `receiver.py:sample_frame()`, `receiver_fountain.py:sample_frame()`
- Pattern: `frame[half_block::BLOCK_SIZE, half_block::BLOCK_SIZE]` (sequential) or parameterized with `offset_x/y` and `scale_x/y` for alignment correction (fountain)

## Entry Points

**sender.py:**
- Location: `sender.py:main()`
- Triggers: CLI `python sender.py <file_or_dir> [--fps N] [--redundancy N] [--screen N]`
- Responsibilities: Arg parsing, optional zip, file read, monitor detection, OpenCV fullscreen window, frame display loop with pause/interrupt

**sender.html:**
- Location: `sender.html` (browser entry point)
- Triggers: Opened in browser, user selects file and clicks Start
- Responsibilities: File read via FileReader, fountain encoding, requestAnimationFrame render loop, canvas rendering

**receiver.py:**
- Location: `receiver.py:main()`
- Triggers: CLI `python receiver.py <camera_index> [--output dir]`
- Responsibilities: Camera open, capture loop, frame decode, completion detection, file reassembly and save

**receiver_fountain.py:**
- Location: `receiver_fountain.py:main()`
- Triggers: CLI `python receiver_fountain.py <camera_index> [--output dir]`
- Responsibilities: Camera open, fountain decode loop, FountainDecoder management, completion detection, file save

## Error Handling

**Strategy:** Pragmatic / fail-soft. Missing frames noted with warnings, file saved even if incomplete.

**Patterns:**
- `struct.unpack` wrapped in try/except, returns None tuple on parse failure (`receiver.py:decode_frame()`)
- Missing sequential frames filled with zero bytes (`receiver.py` reassembly loop)
- Fountain receiver silently ignores decode errors via bare `except Exception: pass`
- K sanity check in fountain receiver: `if K == 0 or K > 60000: continue`
- Metadata parse failure falls back to raw dump: saves `dump.bin` (sequential) or timestamped `.bin` (fountain)

## Cross-Cutting Concerns

**Logging:** `print()` to stdout; progress via `sys.stdout.write` with `\r` overwrite for frame counters

**Validation:** Minimal. Header sanity checks on data_len vs BYTES_PER_FRAME, K bounds check. No checksum or CRC on file content.

**Authentication:** None — no authentication or encryption of transmitted data.

---

*Architecture analysis: 2026-02-16*
