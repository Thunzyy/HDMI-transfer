# Coding Conventions

**Analysis Date:** 2026-02-16

## Naming Patterns

**Files:**
- Lowercase with underscores: `sender.py`, `receiver.py`, `receiver_fountain.py`, `common.py`
- Test files prefixed with `test_`: `tests/test_loopback.py`
- Descriptive names that reflect role: `common.py` for shared config

**Functions:**
- Lowercase with underscores (snake_case): `encode_frame`, `decode_frame`, `sample_frame`, `get_monitors`, `create_calibration_frame`
- Verb-noun pattern for actions: `generate_random_file`, `decode_frame_data`
- Entry point always named `main()`

**Variables:**
- Lowercase snake_case: `file_data`, `total_frames`, `start_time`, `output_path`
- Single-letter loop variables: `i`, `r`, `f`
- Descriptive for important state: `received_chunks`, `max_frame_index`, `total_frames_expected`

**Constants:**
- UPPER_SNAKE_CASE defined in `common.py`: `WIDTH`, `HEIGHT`, `BLOCK_SIZE`, `HEADER_SIZE`, `BYTES_PER_FRAME`
- Local constants inline in code: `HEADER_LEN = 6` in `receiver_fountain.py`

**Classes:**
- PascalCase: `PRNG`, `FountainDecoder`, `RECT`
- Methods: lowercase snake_case: `next()`, `next_float()`, `add_droplet()`, `resolve_chunk()`, `is_complete()`, `get_file_data()`

## Code Style

**Formatting:**
- No linting or formatting tools configured (no `.flake8`, `pyproject.toml`, `.pylintrc`, or `setup.cfg`)
- 4-space indentation throughout (standard Python)
- No trailing whitespace enforced

**Line Length:**
- No enforced limit; some lines exceed 100 characters (e.g., `sender.py` line 39, 195-196)

**Blank Lines:**
- Single blank line between methods
- Double blank line between top-level functions/classes (mostly followed)

**Imports:**
- Standard library imports listed individually per module, alphabetically loosely
- `from common import *` wildcard used in all modules — imports all constants
- No `__all__` defined in `common.py`
- No third-party / stdlib separation grouping

## Import Organization

**Order (observed in `sender.py`, `receiver.py`, `receiver_fountain.py`):**
1. Third-party library imports (`cv2`, `numpy`)
2. Standard library imports (`os`, `sys`, `struct`, `time`, `argparse`, `math`, etc.)
3. Local imports (`from common import *`)

**No import aliases** used except `import numpy as np`.

**Path Aliases:** None — uses `from common import *` for shared constants.

## Error Handling

**Patterns:**
- Bare `except Exception as e:` blocks used frequently for catch-all handling
  - `sender.py` line 166: monitor detection failures fall back to manual offset
  - `receiver.py` lines 211-234: metadata parsing failures fall back to `dump.bin`
  - `receiver_fountain.py` lines 316-318: entire frame processing is silently swallowed
- Return `None` tuples on decode failures: `return None, None, None, None` in `receiver.py`
- Sanity checks via early `continue` with no logging: `receiver_fountain.py` line 262
- Some silenced exceptions with commented-out print: `receiver_fountain.py` lines 313, 317

**Pattern example:**
```python
try:
    frame_index, total_frames, data_len = struct.unpack('>III', header)
except struct.error:
    return None, None, None, None
```

**Fatal errors:**
- `print(f"Error: ...")` followed by `return` from `main()` — no `sys.exit()` used
- No custom exception classes defined

## Logging

**Framework:** `print()` and `sys.stdout.write()` for all output; no logging module.

**Patterns:**
- Progress updates via `sys.stdout.write(f"\r...")` with `sys.stdout.flush()` for in-place terminal updates
- Informational status: `print(f"...")` with f-strings
- Warnings printed inline: `print(f"WARNING: ...")`
- Debug output commented out rather than removed: `# print(f"DEBUG: ...")` in `receiver_fountain.py` line 52

## Comments

**When to Comment:**
- Block comments explain algorithm steps within functions
- Inline comments explain non-obvious operations (bit manipulation, struct packing)
- Comments describe WHY (e.g., `# We use 0 or 255 values to be robust against noise.`)
- TODO-style notes in comments: `# Optimization: Use array slicing if alignment is perfect.`

**Docstrings:**
- Single-line docstrings on all public functions: `"""Encodes a chunk of bytes into a frame image using robust 3-bit encoding."""`
- Classes have no docstrings (`FountainDecoder`, `PRNG`)
- No parameter/return type documentation in docstrings

**Example:**
```python
def encode_frame(data_chunk, frame_index, total_frames):
    """Encodes a chunk of bytes into a frame image using robust 3-bit encoding."""
```

## Function Design

**Size:** Functions can be large; `main()` in `sender.py` is ~170 lines, `main()` in `receiver_fountain.py` is ~165 lines — exceeds recommended 50-line guideline.

**Parameters:** Positional, no type hints used anywhere in the codebase.

**Return Values:**
- Single return value or tuple: `return img`, `return frame_index, total_frames, data, data_len`
- `None` (implicit or explicit) on error paths

## Module Design

**Exports:**
- `common.py` exports all constants via module-level assignments; no `__all__`
- Consumers use `from common import *` — imports all names into namespace

**Entry Points:**
- All executable scripts use `if __name__ == "__main__": main()` guard

**Type Hints:** None used anywhere in the codebase.

**Binary Protocol Conventions:**
- Big-endian byte order (`>`) used consistently in all `struct.pack`/`struct.unpack` calls
- Header format: `struct.pack('>III', frame_index, total_frames, len(data_chunk))` — 3x uint32
- Filename metadata prefix: `[4 bytes name_len][name_bytes][file_content]`

---

*Convention analysis: 2026-02-16*
