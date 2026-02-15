# Codebase Structure

**Analysis Date:** 2026-02-16

## Directory Layout

```
HDMI_exfil/
├── common.py             # Shared configuration constants (resolution, block size, capacities)
├── sender.py             # Python CLI sender — sequential mode
├── sender.html           # Browser-based fountain sender (standalone HTML+JS)
├── receiver.py           # Python CLI receiver — sequential mode
├── receiver_fountain.py  # Python CLI receiver — fountain code mode
├── requirements.txt      # Python dependencies (opencv-python, numpy)
├── README.md             # Project overview and usage
├── TODO.me               # Short-form TODO notes
├── received_files/       # Default output directory for received files
├── tests/
│   ├── test_loopback.py  # End-to-end encode/decode loopback test (sequential mode)
│   └── data/             # Test data directory
├── .planning/
│   └── codebase/         # GSD codebase analysis documents
└── __pycache__/          # Python bytecode cache (generated)
```

## Directory Purposes

**Root (`/`):**
- Purpose: All application code lives at root level — flat structure
- Contains: All Python modules, the HTML sender, config, requirements
- Key files: `common.py`, `sender.py`, `receiver.py`, `receiver_fountain.py`, `sender.html`

**`received_files/`:**
- Purpose: Default output directory where receiver saves decoded files
- Contains: Files received from transmission sessions
- Generated: Yes (created at runtime by receiver if missing)
- Committed: Directory committed empty (no files tracked)

**`tests/`:**
- Purpose: Automated tests for encode/decode correctness
- Contains: `test_loopback.py` (sequential encode+decode round-trip), `data/` subdir for test assets
- Key files: `tests/test_loopback.py`

**`tests/data/`:**
- Purpose: Test fixture files for use in tests
- Contains: Static binary or text files used as test inputs

**`.planning/codebase/`:**
- Purpose: GSD codebase analysis documents
- Generated: Yes (by `/gsd:map-codebase` command)
- Committed: Yes

**`__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes (by Python interpreter)
- Committed: No (should be in .gitignore)

## Key File Locations

**Entry Points:**
- `sender.py`: CLI sender for sequential encoding mode
- `sender.html`: Browser sender for fountain encoding mode (open directly in browser)
- `receiver.py`: CLI receiver for sequential decoding mode
- `receiver_fountain.py`: CLI receiver for fountain decoding mode

**Configuration:**
- `common.py`: All shared constants — WIDTH, HEIGHT, BLOCK_SIZE, HEADER_SIZE, BYTES_PER_FRAME
- `requirements.txt`: Python package dependencies

**Core Logic:**
- `sender.py:encode_frame()`: Converts a bytes chunk to a NumPy image (sequential)
- `receiver.py:decode_frame()`: Extracts bytes from a sampled block grid (sequential)
- `receiver_fountain.py:FountainDecoder`: Belief-propagation fountain code decoder
- `sender.html` (inline JS): `buildDroplet()`, `renderLoop()`, PRNG implementation

**Testing:**
- `tests/test_loopback.py`: Loopback test for sequential encode/decode pipeline

## Naming Conventions

**Files:**
- Snake_case for Python modules: `sender.py`, `receiver.py`, `receiver_fountain.py`, `common.py`
- Descriptive suffix for variant: `receiver_fountain.py` = fountain variant of receiver
- Single HTML file for browser sender: `sender.html`

**Directories:**
- Snake_case: `received_files/`, `tests/`

**Functions (Python):**
- Snake_case: `encode_frame`, `decode_frame`, `sample_frame`, `create_calibration_frame`

**Constants (Python):**
- SCREAMING_SNAKE_CASE in `common.py`: `WIDTH`, `HEIGHT`, `BLOCK_SIZE`, `BYTES_PER_FRAME`

**Classes (Python):**
- PascalCase: `PRNG`, `FountainDecoder`

## Where to Add New Code

**New encoding mode (e.g., Gray code, QR codes):**
- Encoding logic: new file at root, e.g., `sender_<mode>.py`
- Decoding logic: new file at root, e.g., `receiver_<mode>.py`
- Shared constants: add to `common.py`

**New configuration parameter:**
- Add to `common.py` — all sender/receiver modules import `from common import *`

**New test:**
- Add to `tests/`, follow pattern in `tests/test_loopback.py`
- Place test data files in `tests/data/`

**Received output:**
- Files saved by receiver go to `received_files/` by default (configurable via `--output`)

## Special Directories

**`received_files/`:**
- Purpose: Runtime output for decoded files
- Generated: Yes (created by receiver at runtime)
- Committed: Directory structure only (no content)

**`__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-02-16*
