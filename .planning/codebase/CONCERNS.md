# Codebase Concerns

**Analysis Date:** 2026-02-16

## Tech Debt

**Windows-Only sender.py:**
- Issue: `sender.py` imports `ctypes.windll` and `wintypes` at module level. This causes an immediate `AttributeError` on Linux/macOS, even if `get_monitors()` is never called.
- Files: `/home/lucas/Desktop/HDMI_exfil/sender.py` lines 11-12
- Impact: `sender.py` cannot be imported or run on non-Windows platforms. `tests/test_loopback.py` imports `from sender import encode_frame`, meaning the test suite fails on Linux/macOS.
- Fix approach: Guard the import inside `get_monitors()` with `try/except ImportError` or `if sys.platform == 'win32'`.

**Hardcoded Windows Capture Backend:**
- Issue: Both `receiver.py` and `receiver_fountain.py` use `cv2.VideoCapture(source, cv2.CAP_DSHOW)`, which is a DirectShow flag exclusive to Windows.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` line 94, `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` line 170
- Impact: Receiver silently fails or raises on Linux/macOS. CAP_DSHOW=700 is ignored as unknown on some OpenCV builds and may cause silent no-open.
- Fix approach: Use `cv2.CAP_ANY` (0) or detect platform and choose appropriate backend.

**Stale / Broken Test:**
- Issue: `tests/test_loopback.py` calls `encode_frame(chunk, i)` with 2 arguments, but `sender.encode_frame` requires 3 (`data_chunk`, `frame_index`, `total_frames`). Also calls `decode_frame(sampled)` expecting 3 return values, but `receiver.decode_frame` returns 4.
- Files: `/home/lucas/Desktop/HDMI_exfil/tests/test_loopback.py` lines 40, 48-49
- Impact: Running the test raises `TypeError` immediately. Test suite provides zero coverage.
- Fix approach: Update call signatures to match current API: `encode_frame(chunk, i, total_frames)` and unpack 4 values `idx, total, data, length = decode_frame(sampled)`.

**Duplicate / Diverged sample_frame Implementations:**
- Issue: `receiver.py` and `receiver_fountain.py` both define `sample_frame()` with different signatures and slightly different logic. They are not shared via `common.py`.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` lines 10-37, `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` lines 123-151
- Impact: A fix or improvement applied to one receiver is not reflected in the other. The fountain variant has configurable `offset_x/y` and `scale_x/y`; the basic receiver does not, making them diverge further over time.
- Fix approach: Move the advanced `sample_frame` (with offset/scale) to `common.py` and import in both receivers.

**Diverged Encoding Schemes Between sender.py and sender.html:**
- Issue: `sender.py` encodes 3 bits per block (one bit per RGB channel using 0/255). `sender.html` encodes 1 bit per block (black/white only). The frame structures are completely different: `sender.py` uses a 12-byte header (index + total + length); `sender.html` uses a 6-byte header (seed + K) for fountain codes.
- Files: `/home/lucas/Desktop/HDMI_exfil/sender.py`, `/home/lucas/Desktop/HDMI_exfil/sender.html`, `/home/lucas/Desktop/HDMI_exfil/common.py`
- Impact: `receiver.py` cannot decode frames from `sender.html` and vice versa. `common.py` constants (especially `BYTES_PER_FRAME`) do not apply to the HTML sender at all. The project has two incompatible protocols with no documentation of which is preferred.
- Fix approach: Document in README that `sender.html + receiver_fountain.py` is one system, and `sender.py + receiver.py` is another. Separate `common.py` into two config modules, or parameterize by mode.

**Magic Numbers Throughout:**
- Issue: Values like `128` (threshold), `0x9e3779b9` (PRNG constant), `60000` (sanity limit for K), `1024` (max filename length), `HEADER_LEN = 6` (redefined inline in `receiver_fountain.py` ignoring `HEADER_SIZE` from `common.py`) are scattered as literals with no named constant.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` line 46, `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` lines 185, 262, 291
- Impact: Changes require hunting all occurrences; `HEADER_SIZE = 12` in `common.py` is ignored by `receiver_fountain.py` which defines its own `HEADER_LEN = 6`.
- Fix approach: Define named constants in `common.py` for threshold, header sizes for each protocol variant.

**Python-Loop XOR in FountainDecoder:**
- Issue: `FountainDecoder.add_droplet` and `resolve_chunk` perform per-byte XOR using a Python `for i in range(len(data))` loop.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` lines 69-71, 103-104
- Impact: This is orders of magnitude slower than `numpy` XOR for large payloads. With `PAYLOAD_SIZE = 4044` bytes and potentially thousands of droplets, this is a major throughput bottleneck on the receiver side.
- Fix approach: Convert chunk data to `numpy` arrays and use `np.bitwise_xor` or `^=`.

## Known Bugs

**encode_frame Progress Calculation Off-By-One:**
- Symptoms: Progress printed as `(frame_index + 1)/total_frames` but `frame_index` is 0-based, so the first frame shows 1/N. No actual bug, but the last frame shows `total_frames/total_frames` (100%) which is correct.
- Files: `/home/lucas/Desktop/HDMI_exfil/sender.py` line 93
- Trigger: Every frame encoding
- Workaround: Not critical, cosmetic only.

**receiver.py Uses max_frame_index for Reassembly Instead of total_frames_expected:**
- Symptoms: If the last frame is missing, `max_frame_index` is less than `total_frames_expected - 1`. Reassembly loop uses `range(max_frame_index + 1)` which silently truncates the data.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` lines 192, 202
- Trigger: Last frame(s) are dropped during capture.
- Workaround: None; file will be silently truncated without warning beyond the missing-frames print.

**Fountain Receiver Silently Swallows All Exceptions:**
- Symptoms: The entire decode pipeline (sample, parse header, add droplet) is wrapped in a bare `except Exception: pass`. Any crash, numpy shape error, or decode failure is silently ignored.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` lines 316-318
- Trigger: Any malformed frame or numpy shape mismatch
- Workaround: Uncomment the debug print to diagnose. Long-term fix: catch specific exceptions and log them.

**seed=0 Skipped But Not Handled Consistently:**
- Symptoms: `sender.html` skips seed 0 (`if (state.seed === 0) state.seed = 1`), but `receiver_fountain.py` has no corresponding skip and will attempt to process a seed-0 packet if one arrives from another source.
- Files: `/home/lucas/Desktop/HDMI_exfil/sender.html` line 270, `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` line 262 (only checks `K == 0`)
- Trigger: Seed value wraps around or external data arrives with seed=0
- Workaround: Not a practical concern given sequential seed increment from 1, but fragile.

## Security Considerations

**Arbitrary File Write via Received Filename:**
- Risk: The receiver trusts the filename decoded from the transmission and writes to `os.path.join(output_path, filename)`. In `receiver.py`, `os.path.basename()` is NOT applied before joining. A malicious sender can transmit a filename like `../../etc/cron.d/backdoor` and write outside the output directory.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` lines 213, 223
- Current mitigation: None in `receiver.py`. `receiver_fountain.py` line 294 does apply `os.path.basename(name)` correctly.
- Recommendations: Apply `os.path.basename()` to the filename in `receiver.py` before constructing the save path, matching the pattern in `receiver_fountain.py`.

**No Input Validation on Header Fields:**
- Risk: `receiver.py` sanity-checks `data_len > BYTES_PER_FRAME or data_len == 0` but does not check `frame_index` or `total_frames` for unreasonable values (e.g., `total_frames = 0xFFFFFFFF`). This could cause the receiver to allocate a huge dict or loop for an impossibly large number of frames.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` line 69
- Current mitigation: `total_frames_expected` is set once from the first valid frame; subsequent frames with differing `total_frames` are accepted without verification.
- Recommendations: Add range checks: `if frame_index > 100000 or total_frames > 100000: return None, None, None, None`.

**Zip Archive Created in Current Working Directory:**
- Risk: When a directory is passed to `sender.py`, `shutil.make_archive` creates a zip file in the current working directory with a name derived from the directory basename. This could overwrite an existing file with that name.
- Files: `/home/lucas/Desktop/HDMI_exfil/sender.py` lines 114-118
- Current mitigation: None.
- Recommendations: Use a temp directory (`tempfile.mkdtemp()`) and clean up after transmission.

## Performance Bottlenecks

**Debug Grid Drawn Every Frame in receiver.py:**
- Problem: `receiver.py` draws a full debug grid (cyan lines every 5 blocks = 240 lines + 135 lines = 375 `cv2.line` calls) on every captured frame, even during production use.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` lines 129-135
- Cause: No flag to disable debug rendering; it runs unconditionally.
- Improvement path: Add a `--debug` CLI flag; skip grid drawing unless the flag is set.

**Python-Loop XOR in FountainDecoder (see Tech Debt):**
- Problem: XOR over 4044-byte arrays in pure Python.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` lines 69-71, 103-104
- Cause: Using `bytearray` with a `for` loop instead of numpy vectorized ops.
- Improvement path: Convert to `np.frombuffer` + `^=`.

**sender.py Pre-encodes Nothing; Frames Are Built On-The-Fly:**
- Problem: Each frame is encoded during the display loop, including numpy operations. At 240 FPS, the encoding time per frame must stay under ~4ms. For large files, the GIL and Python overhead may cause frame drops.
- Files: `/home/lucas/Desktop/HDMI_exfil/sender.py` lines 208-213
- Cause: No pre-encoding or frame caching.
- Improvement path: Pre-encode all frames into a list before starting the display loop, or use a producer thread.

## Fragile Areas

**Frame Timing Relies on cv2.waitKey:**
- Files: `/home/lucas/Desktop/HDMI_exfil/sender.py` lines 219-220
- Why fragile: `cv2.waitKey(delay)` does not guarantee precise timing; it depends on OS scheduling and rendering overhead. At 240 FPS (delay=4ms), any processing overhead causes frame drops that corrupt the transmission.
- Safe modification: If changing FPS or adding any per-frame processing, profile carefully. For production, replace with a separate frame-clock or use `sender.html` which uses `requestAnimationFrame`.
- Test coverage: No timing tests exist.

**sample_frame Alignment Assumption:**
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` lines 29-32
- Why fragile: The comment explicitly warns that `frame[half_block::BLOCK_SIZE, half_block::BLOCK_SIZE]` assumes perfect pixel-alignment between sender and capture card. Any scaling or cropping by the capture card hardware will cause systematic decode errors. The fountain receiver adds manual offset/scale tuning as a workaround, but the basic receiver has no such compensation.
- Safe modification: Test alignment visually before capturing. Do not change `BLOCK_SIZE` without verifying the capture card output.
- Test coverage: `test_loopback.py` tests only perfect-alignment (simulated, no actual capture).

**FountainDecoder chunk_to_droplets Mapping Not Cleaned Up:**
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` lines 86-87, 96-109
- Why fragile: Resolved droplets remain in `self.droplets` and in `chunk_to_droplets` values. For a long transmission (many droplets), memory grows unboundedly. Droplets whose `indices` set is emptied (all chunks known) are never removed.
- Safe modification: Decoding small files is fine. For large files (>100MB), memory pressure may cause slowdowns or OOM.
- Test coverage: None.

**total_frames_expected Set Only Once, Never Validated:**
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` lines 152-155
- Why fragile: If a spurious valid-looking frame arrives before the real transmission with a different `total_frames`, the receiver locks onto the wrong expected count and will either never complete or complete early.
- Safe modification: Add a consistency check: if a new frame arrives with a different `total_frames` value, warn and possibly reset state.
- Test coverage: None.

## Scaling Limits

**K Field in Fountain Protocol Limited to 16-bit (uint16):**
- Current capacity: `K` is encoded as a `uint16` in `sender.html` (line 263: `view.setUint16(4, state.K, false)`) and decoded as `>H` in `receiver_fountain.py` (line 257).
- Limit: Maximum 65535 chunks. At `PAYLOAD_SIZE = 4044` bytes/chunk, maximum file size is ~265MB.
- Scaling path: Change to `uint32` in both sender and receiver; update `HEADER_LEN` from 6 to 8 bytes.

**frame_index Field in Basic Protocol Limited to uint32:**
- Current capacity: `frame_index` encoded as `>I` (4 bytes unsigned). At `BYTES_PER_FRAME` (~32KB), max file size is ~140TB.
- Limit: Not a practical concern.

## Dependencies at Risk

**No Version Pins in requirements.txt:**
- Risk: `requirements.txt` lists `opencv-python` and `numpy` without version constraints. Breaking API changes in either library (e.g., OpenCV 5.x changes in `CAP_PROP_*` constants) will cause silent failures or crashes.
- Impact: Any `pip install` after a major version release could break the project.
- Migration plan: Pin to known-good versions, e.g., `opencv-python==4.9.0.80` and `numpy==1.26.4`. Add a `.python-version` file.

**ctypes.windll Dependency Limits Portability:**
- Risk: `sender.py` directly uses Windows-only `ctypes.windll`. There is no abstract screen-detection layer.
- Impact: sender is permanently tied to Windows unless refactored.
- Migration plan: Use `screeninfo` or `PyQt5/6` for cross-platform monitor detection, or restrict `sender.py` usage documentation to Windows only.

## Missing Critical Features

**No Error Correction in Basic Protocol:**
- Problem: `sender.py + receiver.py` uses a sequential frame protocol with no error correction. A single dropped frame produces a zeroed gap in the output file (or truncation if the last frame is dropped).
- Blocks: Reliable transmission over noisy HDMI capture paths.

**No Integrity Verification:**
- Problem: Neither the basic nor fountain protocol includes a checksum or hash of the transmitted file. The receiver has no way to know if the reconstructed file is bit-perfect without external comparison.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver.py` lines 183-234, `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py` lines 280-309
- Risk: Silent data corruption goes undetected.

**No Cross-Platform Sender for Python:**
- Problem: `sender.html` works cross-platform (browser), but `sender.py` is Windows-only. There is no Python sender that works on Linux or macOS.
- Blocks: Use on Kali Linux (the development platform per OS detection).

## Test Coverage Gaps

**Test Suite Is Broken and Has No CI:**
- What's not tested: Everything. The single test file `tests/test_loopback.py` has mismatched API calls and cannot run.
- Files: `/home/lucas/Desktop/HDMI_exfil/tests/test_loopback.py`
- Risk: Regressions go undetected. No way to verify encode/decode round-trip correctness.
- Priority: High

**Fountain Protocol Has Zero Tests:**
- What's not tested: `FountainDecoder`, `PRNG`, `receiver_fountain.py` decode pipeline, sender.html `chooseIndices` / `buildDroplet` logic.
- Files: `/home/lucas/Desktop/HDMI_exfil/receiver_fountain.py`, `/home/lucas/Desktop/HDMI_exfil/sender.html`
- Risk: PRNG mismatch between Python and JS would cause 0% decode success with no failing test to catch it.
- Priority: High

**No Noise/Compression Robustness Tests:**
- What's not tested: The comment in `tests/test_loopback.py` line 43 acknowledges that noise simulation is missing. Robustness to JPEG/MJPEG artifacts (the primary real-world failure mode) is not tested.
- Files: `/home/lucas/Desktop/HDMI_exfil/tests/test_loopback.py` lines 43-44
- Risk: A protocol parameter change that degrades real-world performance (e.g., smaller BLOCK_SIZE) will pass the loopback test but fail in practice.
- Priority: Medium

---

*Concerns audit: 2026-02-16*
