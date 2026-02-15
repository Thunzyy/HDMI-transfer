# Technology Stack

**Analysis Date:** 2026-02-16

## Languages

**Primary:**
- Python 3.8+ - Core sender/receiver logic (`sender.py`, `receiver.py`, `receiver_fountain.py`, `common.py`)

**Secondary:**
- HTML5/JavaScript (vanilla, no framework) - Browser-based fountain sender (`sender.html`)
- CSS3 - Styling for the browser UI in `sender.html`

## Runtime

**Environment:**
- CPython 3.8+ (confirmed via `__pycache__` containing `cpython-313.pyc` artifacts, meaning 3.13 is in use locally)
- Browser: Any modern browser supporting Canvas API, FileReader API, requestAnimationFrame, TypedArrays, DataView

**Package Manager:**
- pip (implied by `requirements.txt`)
- Lockfile: Not present (no `requirements.lock` or `pip.lock`)

## Frameworks

**Core:**
- No web framework - pure Python scripts invoked via CLI
- No Python async framework - synchronous blocking I/O and OpenCV event loops

**Testing:**
- No test framework (unittest, pytest) - `tests/test_loopback.py` is a standalone script using `assert`-free manual checks and print output; run directly with `python tests/test_loopback.py`

**Build/Dev:**
- No build toolchain (no setuptools, pyproject.toml, Makefile)
- `sender.html` has no build step - open directly in a browser

## Key Dependencies

**Critical:**
- `opencv-python` (version unspecified in `requirements.txt`) - Video capture via `cv2.VideoCapture`, frame rendering via `cv2.imshow`, image manipulation, window management in `sender.py`, `receiver.py`, `receiver_fountain.py`
- `numpy` (version unspecified in `requirements.txt`) - High-performance pixel array operations, bit packing/unpacking (`np.packbits`, `np.unpackbits`, array slicing), frame encoding/decoding in all Python modules

**Standard Library (no install required):**
- `struct` - Binary header packing/unpacking in `sender.py`, `receiver.py`, `receiver_fountain.py`
- `ctypes` / `ctypes.wintypes` - Windows API calls for multi-monitor detection in `sender.py`
- `shutil` - Directory zipping via `shutil.make_archive` in `sender.py`
- `argparse` - CLI argument parsing in `sender.py`, `receiver.py`, `receiver_fountain.py`
- `os`, `sys`, `math`, `time` - Utility functions throughout

## Configuration

**Environment:**
- No `.env` file or environment variables used
- Configuration is centralized in `common.py` as module-level constants:
  - `WIDTH = 1920`, `HEIGHT = 1080` - display/capture resolution
  - `BLOCK_SIZE = 8` - pixel block size (must match between sender and receiver)
  - `HEADER_SIZE = 12` - frame header size in bytes
  - Derived constants: `COLS`, `ROWS`, `BLOCKS_PER_FRAME`, `BITS_PER_FRAME`, `BYTES_PER_FRAME`
- `sender.html` duplicates these constants inline in JavaScript (`const WIDTH`, `const HEIGHT`, `const BLOCK_SIZE`, etc.)

**Build:**
- No build config files present

## Platform Requirements

**Development:**
- Python 3.8+ with pip
- `pip install opencv-python numpy`
- `sender.py` explicitly uses Windows-only API: `ctypes.windll.user32` and `EnumDisplayMonitors` for monitor detection; fallback exists for non-Windows but the primary code path is Windows
- `receiver.py` and `receiver_fountain.py` use `cv2.CAP_DSHOW` (DirectShow, Windows-only) for video capture
- `sender.html` runs in any browser without install

**Production:**
- Hardware requirement: Sender machine must have HDMI output; Receiver machine must have a USB/PCIe video capture card
- Physical HDMI cable connecting sender display output to capture card input
- No server deployment - fully local/air-gapped tool

---

*Stack analysis: 2026-02-16*
