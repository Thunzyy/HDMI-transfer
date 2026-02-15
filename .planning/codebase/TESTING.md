# Testing Patterns

**Analysis Date:** 2026-02-16

## Test Framework

**Runner:**
- No formal test framework configured (no pytest, unittest, or nose setup)
- Test file `tests/test_loopback.py` is a standalone script executed directly with Python
- No `pytest.ini`, `setup.cfg [tool:pytest]`, or `pyproject.toml` present

**Assertion Library:**
- No assertion library — uses `print("SUCCESS: ...")` / `print("FAILURE: ...")` pattern
- No `assert` statements used

**Run Commands:**
```bash
python tests/test_loopback.py    # Run loopback integration test directly
```

## Test File Organization

**Location:**
- Separate `tests/` directory at project root
- Test data in `tests/data/testfile.txt` (contains: "test simple file transfert")

**Naming:**
- Files: `test_<feature>.py` — `tests/test_loopback.py`
- Functions: `test_<description>()` — `test_loopback()`

**Structure:**
```
tests/
├── data/
│   └── testfile.txt
└── test_loopback.py
```

## Test Structure

**Suite Organization:**

The single test file is a script with a helper function and one test function:
```python
def generate_random_file(filename, size_kb):
    """Creates a random binary file of given size."""
    ...

def test_loopback():
    """Full encode/decode cycle for all frames."""
    ...

if __name__ == "__main__":
    test_loopback()
```

**Patterns:**
- Setup: generates a 100KB random binary file at test start
- Core loop: encodes each frame with `encode_frame()` then immediately decodes with `sample_frame()` + `decode_frame()`
- Teardown: removes temporary files (`test_data.bin`, `test_output.bin`) after test
- Verification: byte-exact comparison of original vs decoded data

## Mocking

**Framework:** None used.

**Patterns:**
- No mocking library imports
- Hardware I/O (OpenCV camera, display windows) is avoided by calling encode/decode functions directly without `cv2.VideoCapture` or `cv2.imshow`
- "Perfect transmission" simulated by passing encoded frame directly to decoder without noise

**Example of simulated transmission:**
```python
# Encode
frame_img = encode_frame(chunk, i)

# Simulate transmission (perfect quality)
# In real life, we'd add noise or compression artifacts here to test robustness
received_frame = frame_img

# Decode
sampled = sample_frame(received_frame)
idx, data, length = decode_frame(sampled)
```

**What to Mock:**
- `cv2.VideoCapture` — not mocked; camera tests not attempted
- `cv2.imshow` / window operations — not mocked; display tests not attempted
- File I/O — not mocked; uses real temp files written to disk

**What NOT to Mock:**
- `encode_frame` / `decode_frame` — these are the units under test
- `struct.pack` / `struct.unpack` — low-level, not mocked

## Fixtures and Factories

**Test Data:**
```python
def generate_random_file(filename, size_kb):
    size = size_kb * 1024
    with open(filename, 'wb') as f:
        f.write(os.urandom(size))
```

**Location:**
- Helper defined inline in `tests/test_loopback.py`
- Static fixture file: `tests/data/testfile.txt` — not used by the current test, present for manual testing

## Coverage

**Requirements:** None enforced — no coverage configuration or CI pipeline.

**View Coverage:**
```bash
# Not configured, but could run:
python -m pytest tests/ --cov=. --cov-report=term
```

## Test Types

**Unit Tests:**
- Not present — no isolated unit tests for individual functions (e.g., `encode_frame` in isolation with controlled input)

**Integration Tests:**
- `tests/test_loopback.py` — end-to-end loopback test exercising full encode → frame image → decode pipeline
- Tests the full data path: file bytes → frame grid → sampled pixels → decoded bytes

**E2E Tests:**
- Not used — no automated tests involving actual camera capture or display output

## Common Patterns

**Async Testing:**
- Not applicable — codebase is synchronous only

**Error Testing:**
- No negative/error path tests present
- No tests for: corrupted frames, missing frames, struct.error on bad headers, mismatched frame counts

**Data Integrity Pattern:**
```python
if decoded_data == file_data:
    print("SUCCESS: Decoded data matches original file!")
else:
    print("FAILURE: Decoded data does not match.")
    print(f"Original len: {len(file_data)}, Decoded len: {len(decoded_data)}")
```

## Gaps and Notes

- The test in `tests/test_loopback.py` calls `encode_frame(chunk, i)` with 2 args, but the current `sender.py` signature is `encode_frame(data_chunk, frame_index, total_frames)` — **this test is broken and will fail with a TypeError**.
- No test runner integration (no pytest marks, no test discovery config)
- `FountainDecoder` and `PRNG` classes in `receiver_fountain.py` have zero test coverage
- No CI/CD pipeline to run tests automatically
- Tests use disk I/O for temp files instead of `io.BytesIO` in-memory buffers

---

*Testing analysis: 2026-02-16*
