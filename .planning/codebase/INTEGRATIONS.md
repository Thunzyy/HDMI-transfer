# External Integrations

**Analysis Date:** 2026-02-16

## APIs & External Services

None. This project is fully offline and air-gapped by design. It communicates exclusively via physical HDMI video signals. No network requests, no cloud services, no external APIs.

## Data Storage

**Databases:**
- None. No database is used.

**File Storage:**
- Local filesystem only
- Received files are saved to `received_files/` directory by default (configurable via `--output` CLI argument)
- `sender.py` writes a temporary zip archive to the current working directory when the input path is a directory (`shutil.make_archive`)

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- None. No authentication system exists. The tool is a physical-layer data transfer utility.

## Monitoring & Observability

**Error Tracking:**
- None. Errors are printed to stdout/stderr only.

**Logs:**
- `stdout` print statements with progress indicators (`sys.stdout.write` with `\r` for in-place progress in `sender.py` and `receiver_fountain.py`)
- No structured logging, no log files, no log rotation

## CI/CD & Deployment

**Hosting:**
- Not applicable - local CLI tool, no server

**CI Pipeline:**
- None. No GitHub Actions, no pre-commit hooks, no automated testing pipeline.

## Hardware Integrations

**Video Capture (Receiver Side):**
- Any DirectShow-compatible (Windows) video capture device via `cv2.VideoCapture(source, cv2.CAP_DSHOW)` in `receiver.py` and `receiver_fountain.py`
- Device addressed by integer index (e.g., `0`, `1`, `2`) or file path
- Target resolution forced: `cv2.CAP_PROP_FRAME_WIDTH=1920`, `cv2.CAP_PROP_FRAME_HEIGHT=1080`
- Target FPS: `receiver.py` requests 240 FPS; `receiver_fountain.py` requests 60 FPS

**Display Output (Sender Side - Python):**
- OpenCV fullscreen window via `cv2.WINDOW_FULLSCREEN` in `sender.py`
- Multi-monitor support via Windows API: `ctypes.windll.user32.EnumDisplayMonitors` to enumerate connected displays
- Window positioned on a target monitor using `cv2.moveWindow` with monitor's `left`/`top` pixel offset

**Display Output (Sender Side - Browser):**
- HTML5 Canvas element (1920x1080 pixels) in `sender.html`
- Rendered at CSS `width: 1920px; height: 1080px` with `image-rendering: pixelated`
- Uses `requestAnimationFrame` for render loop; no explicit FPS cap (runs at display refresh rate)
- FileReader API to read local files in the browser without network upload

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

## Environment Configuration

**Required env vars:**
- None. No environment variables are used anywhere in the project.

**Secrets location:**
- Not applicable - no secrets, credentials, or API keys exist in this project.

## Protocol / Wire Format

The only "integration" is the custom binary frame protocol transmitted over HDMI video:

**Standard Mode (`sender.py` / `receiver.py`):**
- Each video frame encodes data as pixel blocks (1 bit per RGB channel, 0=black, 255=white)
- Frame header (12 bytes): `[4B frame_index][4B total_frames][4B data_length]`
- File metadata prefix: `[4B name_len][name_bytes]` prepended to file content
- Frame capacity: `(ROWS * COLS * 3 bits / 8) - 12` bytes per frame at 1920x1080 with BLOCK_SIZE=8

**Fountain Mode (`sender.html` / `receiver_fountain.py`):**
- Implements a Luby Transform (LT) / Fountain code using SplitMix32 PRNG for degree distribution
- Frame header (6 bytes): `[4B seed][2B K]` (seed drives PRNG, K is total chunk count)
- Payload is XOR combination of source chunks selected by PRNG
- Degree distribution: <10% chance degree=1, <60% chance degree=2, else random 1-20
- Allows recovery even with packet (frame) loss - receiver does not need sequential frames
- PRNG algorithm (SplitMix32) is implemented identically in both Python (`receiver_fountain.py`) and JavaScript (`sender.html`) to ensure compatible droplet reconstruction

---

*Integration audit: 2026-02-16*
