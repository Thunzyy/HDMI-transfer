# Domain Pitfalls

**Domain:** HDMI data exfiltration via capture card (data-over-video)
**Project:** HDMI_exfil (Elgato 4K X, fountain codes, 1080p)
**Researched:** 2026-02-16

---

## Critical Pitfalls

Mistakes that cause data corruption, complete transfer failures, or rewrites.

---

### Pitfall 1: Chroma Subsampling Destroys Color-Encoded Data

**What goes wrong:** The Elgato 4K X delivers frames to the host via USB in NV12 (4:2:0), YUY2 (4:2:2), or MJPEG depending on resolution/FPS. At 1080p240, the card uses NV12 (4:2:0 chroma subsampling), which discards 75% of chroma information. The current `sender.py` encodes 3 bits per block (1 per R, G, B channel using 0/255 values), but after 4:2:0 subsampling, the chroma channels (Cb, Cr) are shared across 2x2 pixel groups. For an 8x8 block this might seem safe since the entire block is one color -- but the HDMI-to-USB pipeline converts RGB to YCbCr internally, subsamples the chroma, then OpenCV converts back to BGR. This round-trip introduces color bleeding at block boundaries and can flip threshold decisions on recovered chroma bits, especially at edges where adjacent blocks have different colors.

**Why it happens:** HDMI carries uncompressed RGB, but USB capture cards must compress to fit USB bandwidth. At 1080p240, NV12 requires ~5.97 Gbps which already exceeds USB 3.0's 5 Gbps theoretical max, so the card likely uses MJPEG internally at this rate. MJPEG uses 8x8 DCT blocks with 4:2:0 subsampling, directly corrupting per-pixel color data. Even at 1080p60 with NV12, the 4:2:0 subsampling destroys fine color detail.

**Consequences:**
- Bit errors in the R and B channels (which carry chroma information in YCbCr space)
- The G channel (closest to luma Y) survives best -- which is why `receiver_fountain.py` only reads the green channel (line 157: `bits = (flat[:, 1] > 128)`)
- Silent data corruption: frames decode but contain wrong bits
- The 3-bit RGB encoding in `sender.py` vs the 1-bit (black/white) encoding in `sender.html` is not a bug -- it reflects this exact reality: 1-bit-per-block encoding via luma only is the reliable path through capture card compression

**Warning signs:**
- Bit error rate is higher on R/B channels than G
- Errors cluster at block boundaries
- Transfer works in loopback test but fails through real hardware
- Files decode but checksums fail

**Prevention:**
1. Use luma-only encoding (black/white, 1 bit per block) as the reliable default mode. This survives all chroma subsampling schemes because 0 and 255 in all channels maps cleanly to Y=16 (black) and Y=235 (white) in YCbCr, giving maximum threshold margin.
2. If using multi-bit encoding, encode in YCbCr-aware fashion: use only luma-distinguishable levels (e.g., 4 gray levels per block for 2 bits) rather than relying on color channels.
3. Test through the actual Elgato 4K X hardware at every target FPS, not just in loopback.
4. Add per-frame CRC/checksums so corruption is detected rather than silent.

**Phase mapping:** Must be addressed in the encoding/decoding refactor phase, before any speed optimization. Reliable 1-bit mode first, optional multi-bit mode as a speed differentiator later.

**Confidence:** HIGH -- verified via Elgato 4K X documentation (NV12/MJPEG at high FPS), OpenCV color conversion documentation, and Pen Test Partners' independent research showing 3 bits/pixel (1 per channel, 0/255 extremes) as the survivable threshold for protocol compression.

---

### Pitfall 2: MJPEG 8x8 DCT Block Artifacts Aligned With Data Block Boundaries

**What goes wrong:** MJPEG compresses each frame as an independent JPEG, using 8x8 pixel DCT blocks. The current project uses `BLOCK_SIZE = 8` for data encoding. When MJPEG compression boundaries perfectly align with data block boundaries, DCT ringing artifacts concentrate at exactly the pixel positions being sampled. The center-pixel sampling strategy (`half_block::BLOCK_SIZE` = sampling at pixel 4 of each 8x8 block) sits at the center of a DCT block, where quantization noise is lowest -- but if the alignment shifts by even 1 pixel (due to capture card cropping, scaling, or timing), the sample point moves toward a DCT block boundary where artifacts are worst.

**Why it happens:** The 8x8 DCT block size in JPEG/MJPEG is a fixed standard. Choosing `BLOCK_SIZE = 8` for data encoding creates a resonance effect: compression artifacts and data encoding share the same spatial frequency. Any sub-pixel misalignment between the sender's pixel grid and the capture card's MJPEG encoder grid causes worst-case artifact injection into data samples.

**Consequences:**
- Sporadic bit errors that appear/disappear based on capture alignment
- Errors are non-reproducible between runs (alignment shifts)
- Higher bit error rate than expected given the large threshold margin (0 vs 255)

**Warning signs:**
- Error rate changes when the sender window is moved slightly
- Errors concentrate in specific spatial regions of the frame
- Errors change pattern after capture card reconnection

**Prevention:**
1. Use `BLOCK_SIZE` that is a multiple of 8 but larger (e.g., 16, 24, or 32). This ensures each data block spans multiple MJPEG DCT blocks, and the center-pixel sample is well inside a DCT block regardless of alignment.
2. At `BLOCK_SIZE = 16`: capacity = (1920/16) * (1080/16) = 120 * 67 = 8,040 blocks per frame. At 1 bit per block = 1,005 bytes/frame. At 60 FPS = ~60 KB/s = ~0.48 Mbps. This is the reliability tradeoff.
3. Sample multiple pixels per block and use majority voting rather than single center-pixel sampling.
4. Make `BLOCK_SIZE` configurable and document the speed vs reliability tradeoff.

**Phase mapping:** Address during encoding parameter tuning, after basic refactor. This is a tuning parameter, not an architecture change.

**Confidence:** HIGH -- MJPEG 8x8 DCT blocks are a standard, and the alignment problem is well-documented in video processing literature.

---

### Pitfall 3: Sender/Receiver Encoding Mismatch Between Modes

**What goes wrong:** The codebase currently has two incompatible encoding schemes that cannot interoperate:

| Component | Encoding | Bits/block | Header |
|-----------|----------|------------|--------|
| `sender.py` | 3-bit RGB (0/255 per channel) | 3 | 12 bytes (idx, total, len) |
| `sender.html` + `receiver_fountain.py` | 1-bit B/W (black or white) | 1 | 6 bytes (seed, K) |
| `receiver.py` | 3-bit RGB decode | 3 | 12 bytes (idx, total, len) |

The `sender.py` (3-bit) and `receiver_fountain.py` (1-bit) use completely different frame formats. If a developer accidentally pairs the wrong sender with the wrong receiver, or if the refactor merges them without careful separation, transfers silently produce garbage.

**Why it happens:** Organic prototype evolution. The fountain code path was added as a second mode with different encoding to survive capture card compression (correctly), but the frame format diverged from the original mode without explicit version/mode markers in the frame header.

**Consequences:**
- Silent data corruption when wrong sender/receiver paired
- Confusion during development about which mode is active
- Refactoring risk: merging into a unified architecture requires resolving this fundamental format difference

**Warning signs:**
- "Sanity check" failures on `data_len` or `K` values (these will look like garbage when the wrong decoder runs)
- Frame index values that make no sense (e.g., frame 16,843,009 when you have 10 frames)
- The receiver decodes frames but progress never reaches 100%

**Prevention:**
1. Add a magic number / mode byte as the first bytes of every frame's header. Example: `0xDA7A` for sequential mode, `0xF0C0` for fountain mode.
2. During refactor, define a single `FrameHeader` structure with a version/mode field that both encoder paths produce and both decoder paths validate.
3. Reject frames with unrecognized magic numbers rather than attempting to decode them.
4. Unit test that verifies sender.py frames decode correctly with receiver.py, and sender.html frames decode correctly with receiver_fountain.py.

**Phase mapping:** Must be resolved in the architecture/refactor phase, before any new features. This is the first thing to unify.

**Confidence:** HIGH -- directly observed in the codebase (common.py defines 3-bit constants, sender.html uses 1-bit).

---

### Pitfall 4: PRNG Synchronization Failure Between JavaScript and Python

**What goes wrong:** The fountain code system relies on sender and receiver independently computing the same degree and index set from the same seed. Both `sender.html` (JavaScript) and `receiver_fountain.py` (Python) implement SplitMix32 PRNG. If the implementations produce different outputs for the same seed, the receiver will XOR the wrong chunks together, producing silently corrupted data. JavaScript and Python handle integer arithmetic fundamentally differently:

- JavaScript: uses `Math.imul()` for 32-bit multiply, `|0` for signed 32-bit truncation, `>>>0` for unsigned conversion
- Python: arbitrary-precision integers, must manually mask with `& 0xFFFFFFFF`

The current Python PRNG uses `& 0xFFFFFFFF` masking but does not mask intermediate addition results the same way JavaScript's `|0` would handle signed overflow. The `(self.a | 0)` on line 16 of `receiver_fountain.py` is a no-op in Python (Python's `|0` does not truncate to 32 bits) -- it was copied from the JavaScript idiom but does nothing.

**Why it happens:** Porting PRNG algorithms between languages with different integer semantics is notoriously error-prone. JavaScript's `|0` forces signed 32-bit representation; Python's `|0` is identity. A single bit difference in any PRNG output cascades into completely wrong chunk selection for every subsequent droplet.

**Consequences:**
- Complete decoding failure: receiver thinks it decoded correctly but the data is XOR'd garbage
- Extremely hard to debug: both sides "work" independently, the PRNG "looks correct"
- May work for small files (low K, low degree) and fail for large files (more seeds exercised)

**Warning signs:**
- Fountain decoding reaches 100% but output file is corrupt
- Works for tiny files but fails for larger ones
- Adding debug logging shows different degree sequences for the same seed in JS vs Python

**Prevention:**
1. Create a PRNG test vector file: generate 1000 outputs from seeds [1, 2, 3, ...] in JavaScript, save to JSON, and verify the Python PRNG produces identical outputs. This is a one-time test that catches all cross-language drift.
2. Fix the Python PRNG: remove the meaningless `self.a = (self.a | 0)` line, and ensure every arithmetic step masks to 32 bits: `self.a = (self.a + 0x9e3779b9) & 0xFFFFFFFF`.
3. The `next_float()` division must use the same denominator (`4294967296.0`) and the unsigned value. Verify: `return (self.next() & 0xFFFFFFFF) / 4294967296.0`.
4. Pin this test in CI so future PRNG changes are caught.

**Phase mapping:** Must be verified during the refactor phase. Add cross-language PRNG test vectors as one of the first test artifacts.

**Confidence:** HIGH -- the JavaScript/Python integer semantics difference is well-documented, and the Python code contains the telltale `(self.a | 0)` copied idiom.

---

### Pitfall 5: cv2.waitKey() Cannot Achieve Target Frame Rates Above ~80 FPS

**What goes wrong:** The sender uses `cv2.waitKey(delay)` to control frame timing, with `delay = int(1000 / fps)`. At 240 FPS, `delay = 4ms`. But `cv2.waitKey()` has a minimum effective delay of ~12-13ms on most systems regardless of the parameter value, capping effective display rate at ~75-80 FPS. On Windows, the floor is even worse (~15ms due to timer resolution). This means the sender cannot actually transmit at 240 FPS using `cv2.imshow` + `cv2.waitKey`, even though `--fps 240` is the default argument.

**Why it happens:** `cv2.waitKey()` handles all GUI event processing (window repainting, keyboard input). It waits for a *minimum* of the specified delay. The actual delay is dominated by OS timer resolution (Windows: ~15ms, Linux: ~1ms with `hrtimer`) and GUI event processing overhead. Additionally, `cv2.imshow()` in fullscreen mode adds further overhead.

**Consequences:**
- Sender reports 240 FPS but actually outputs ~60-80 FPS
- Speed calculations are wrong (reported Mbps is inflated)
- Receiver sees duplicate frames or misses the timing assumption
- On Windows specifically, performance is dramatically worse than on Linux

**Warning signs:**
- Actual throughput is much lower than calculated from `BYTES_PER_FRAME * fps`
- Transfer takes 3-4x longer than expected
- Increasing `--fps` beyond ~80 has no effect on actual speed

**Prevention:**
1. Measure actual achieved FPS and report it (compare wall-clock time vs frame count).
2. For high-speed sending, bypass `cv2.imshow` entirely. Options:
   - Use a dedicated GPU-accelerated rendering backend (SDL2, Pygame, GLFW)
   - Write frames directly to a framebuffer device on Linux
   - Use the HTML/canvas sender (`sender.html`) which uses `requestAnimationFrame` and is limited by monitor refresh rate but avoids the `waitKey` bottleneck
3. Separate the frame generation loop from the display loop using threading.
4. On Windows, call `timeBeginPeriod(1)` to improve timer resolution (from winmm.dll), though this has system-wide side effects.

**Phase mapping:** Address during speed optimization phase, after architecture is stable. The HTML sender already partially solves this -- it may become the primary high-speed sender.

**Confidence:** HIGH -- the `cv2.waitKey` timing floor is extensively documented in OpenCV issue trackers and forums, with independent measurements confirming ~12ms minimum on typical systems.

---

## Moderate Pitfalls

Mistakes that cause delays, technical debt, or reduced reliability.

---

### Pitfall 6: Bare Exception Handling Silently Swallows Errors

**What goes wrong:** Both `receiver_fountain.py` (lines 316-318) and the monitor detection in `sender.py` (lines 166-170) use bare `except Exception` blocks that catch all errors and either `pass` silently or print a generic message. During the real-time decode loop, if a frame produces a struct unpacking error, corrupt seed, or NumPy shape mismatch, the error is silently discarded and that frame is lost forever. With sequential (non-fountain) transfers, a single silently-dropped frame means a corrupted file with no indication of where the corruption occurred.

**Why it happens:** Prototype development prioritizes "keep running" over "report precisely." In a real-time capture loop, you don't want one bad frame to crash the program. But the tradeoff is taken too far when *all* error information is discarded.

**Consequences:**
- Debugging transfer failures becomes extremely difficult
- No way to distinguish "capture card produced garbage frame" from "decoder bug"
- Intermittent failures cannot be root-caused
- Performance problems hidden (e.g., every other frame fails to decode but program keeps running)

**Prevention:**
1. Replace bare `except Exception: pass` with typed exception handling: catch `struct.error` for unpacking failures, `ValueError` for shape mismatches, etc.
2. Log errors with rate limiting (e.g., count errors per second, log summary every N seconds) rather than per-frame logging which would flood output.
3. Track error statistics: `frames_received`, `frames_failed_decode`, `frames_failed_sanity_check`. Report these at the end of transfer and periodically during transfer.
4. Never `pass` silently -- at minimum increment an error counter.

**Phase mapping:** Address during the architecture refactor phase. Define a proper error handling strategy before restructuring the decode loop.

**Confidence:** HIGH -- directly observed in the codebase.

---

### Pitfall 7: Windows-Only APIs Block Cross-Platform Use

**What goes wrong:** `sender.py` uses `ctypes.windll.user32.EnumDisplayMonitors` (Windows API) for monitor detection. This immediately crashes on Linux/macOS with `AttributeError: module 'ctypes' has no attribute 'windll'`. The receiver uses `cv2.CAP_DSHOW` (DirectShow, Windows-only) for capture card access. On Linux, this must be `cv2.CAP_V4L2` or omitted (auto-select). These are hard failures -- the program will not start at all on non-Windows platforms.

**Why it happens:** Prototype was developed and tested on Windows only. Monitor detection and capture card access are inherently platform-specific operations.

**Consequences:**
- Cannot run sender on Linux (monitor detection crashes)
- Cannot run receiver on Linux (DirectShow unavailable or ignored)
- Contributors on macOS/Linux cannot test or develop
- CI/CD testing impossible without Windows runners

**Warning signs:**
- `ImportError` or `AttributeError` on `ctypes.windll`
- `cv2.VideoCapture` silently fails to open (returns `cap.isOpened() == False`)
- Different behavior between `CAP_DSHOW`, `CAP_V4L2`, and `CAP_MSMF` backends

**Prevention:**
1. Abstract platform-specific code behind a platform detection layer:
   ```python
   import platform
   if platform.system() == 'Windows':
       from .platform_win import get_monitors, get_capture_backend
   elif platform.system() == 'Linux':
       from .platform_linux import get_monitors, get_capture_backend
   ```
2. For monitor detection on Linux, use `xrandr` subprocess or `screeninfo` library.
3. For capture backend, auto-detect: `cv2.CAP_DSHOW` on Windows, `cv2.CAP_V4L2` on Linux, `cv2.CAP_AVFOUNDATION` on macOS. Or use `cv2.CAP_ANY` with fallback.
4. Use the HTML sender (`sender.html`) as the cross-platform sender path -- browsers handle fullscreen display natively across all platforms.

**Phase mapping:** Address in the cross-platform support phase. Can be deferred if Linux support is not immediately needed, but the abstraction layer should be designed during architecture refactor.

**Confidence:** HIGH -- directly observed in the codebase (`ctypes.windll`, `cv2.CAP_DSHOW`).

---

### Pitfall 8: Fountain Code Degree Distribution is Not Optimized for Small K

**What goes wrong:** The current fountain code degree distribution (in both `sender.html` and `receiver_fountain.py`) uses a simple custom distribution:
- 10% chance of degree 1
- 50% chance of degree 2
- 40% chance of degree `random(1, min(K, 20))`

This is neither the Ideal Soliton Distribution nor the Robust Soliton Distribution from LT code theory. For small K (common with small files -- e.g., a 16KB file with 4044 bytes/chunk = K=4), this distribution generates too few degree-1 droplets for the decoder to start peeling, and the high-degree droplets (up to 20) cover more chunks than exist when K < 20. The result is high overhead (many more droplets needed than K) or outright decoding failure.

**Why it happens:** Implementing the Robust Soliton Distribution requires careful parameter tuning (c, delta) that depends on K. The current ad-hoc distribution was likely tuned by trial and error for one specific file size and works "well enough" for medium K values, but breaks down at the extremes.

**Consequences:**
- Small files (K < 10) may require 3-5x overhead to decode, or fail entirely
- Large files (K > 1000) may have inefficient overhead because the degree cap of 20 is too low relative to K
- Inconsistent performance: "sometimes it works, sometimes it doesn't" depending on file size
- No way to predict required transmission time because overhead is unpredictable

**Warning signs:**
- Decoding stalls at 90-95% (missing chunks that no remaining droplet can resolve)
- Small test files fail to decode while larger files succeed
- Increasing redundancy helps but requires much more than theoretical ~5% overhead

**Prevention:**
1. Implement the Robust Soliton Distribution with parameters tuned for expected K range.
2. For small K (< 50), consider using a simple repetition/interleaving scheme instead of fountain codes -- the overhead of fountain codes is not worthwhile at very small K.
3. Cap degree at `min(degree, K)` to prevent degrees larger than the number of chunks.
4. Add an overhead parameter: allow configuring how many extra droplets (as percentage of K) to send. Default to 20% overhead for small K, 5-10% for large K.
5. Test at extreme K values: K=1 (one chunk), K=5, K=50, K=500, K=5000.

**Phase mapping:** Address during fountain code optimization phase, after architecture is stable. Requires empirical testing with different file sizes.

**Confidence:** MEDIUM -- the custom degree distribution is observed in the code, and the theoretical pitfalls of non-optimal distributions for small K are well-documented in academic literature, but the exact failure behavior for *this specific* distribution would need empirical testing.

---

### Pitfall 9: No Data Integrity Verification (Checksums/CRC)

**What goes wrong:** Neither the sequential nor the fountain receiver verifies data integrity. The sequential receiver checks for missing frames but has no way to detect bit errors within successfully decoded frames. The fountain receiver has no integrity check at all -- `is_complete()` only checks that all K chunks have been resolved, not that they were resolved correctly. A single bit error in an early-decoded chunk propagates through the XOR peeling process, corrupting multiple dependent chunks.

**Why it happens:** Prototype focused on "does it work at all" before adding integrity checking.

**Consequences:**
- Silently corrupted files with no error indication
- User believes transfer succeeded but file is damaged
- In fountain mode, a single corrupted droplet can poison the entire decode through XOR error propagation
- No way to request retransmission (one-way channel) so corruption must be caught and the user must know to retry

**Warning signs:**
- Files transfer "successfully" but cannot be opened
- Zip files fail CRC checks when extracted
- Images have visual artifacts
- Executables crash

**Prevention:**
1. Add per-frame CRC-32 to the frame header. Reject frames that fail CRC before decoding.
2. Add a whole-file hash (SHA-256) in the first frame's metadata. After reassembly, verify the hash and report pass/fail.
3. In fountain mode, add per-chunk CRC so the decoder can verify each resolved chunk before using it in XOR peeling. Discard chunks that fail CRC rather than propagating errors.
4. Display final integrity result prominently: "Transfer complete: SHA-256 VERIFIED" or "Transfer complete: INTEGRITY CHECK FAILED -- retry recommended."

**Phase mapping:** Must be added during the refactor phase. CRC-per-frame is cheap and should be in the first refactored version. Whole-file hash can follow.

**Confidence:** HIGH -- directly observed: no checksums anywhere in the codebase.

---

### Pitfall 10: Refactoring Breaks Working Prototype (The Big Rewrite Trap)

**What goes wrong:** The prototype currently works end-to-end through real hardware. A common failure mode when refactoring working prototypes is attempting to restructure everything at once -- new module boundaries, new encoding format, new error handling, new testing -- and ending up with a system that is architecturally cleaner but functionally broken. The specific risk here is high because:
- The system involves hardware in the loop that is hard to mock
- Timing-sensitive behavior (frame rates, capture timing) may change with restructuring
- The encoding/decoding math must remain bit-exact across refactoring
- Two modes (sequential + fountain) must both keep working

**Why it happens:** Refactoring is seductive: "while we're in here, let's also fix X, Y, and Z." Each additional change multiplies the risk of regressions. Without tests to catch regressions, the first sign of breakage may be a completely failed transfer through hardware.

**Consequences:**
- Days or weeks of debugging to find which change broke which behavior
- Loss of the working baseline (if not properly version-controlled)
- Temptation to "just rewrite from scratch" which resets all empirical tuning
- Loss of confidence in the refactoring effort

**Prevention:**
1. **Establish baseline tests BEFORE refactoring.** Create loopback tests (encode then decode without hardware) for both sequential and fountain modes. Run these tests after every refactoring change.
2. **Refactor incrementally.** One structural change at a time, verified by tests:
   - Step 1: Extract constants to config (test: loopback still works)
   - Step 2: Separate encoding from display (test: loopback still works)
   - Step 3: Add platform abstraction (test: loopback still works)
   - Step 4: Unify frame format (test: loopback still works)
3. **Keep the old code runnable.** Don't delete `sender.py`, `receiver.py` until the refactored versions pass all the same tests.
4. **Tag the working baseline.** `git tag v0.1-working-prototype` before starting any refactoring.
5. **Hardware validation checkpoints.** After every 2-3 structural changes, run an actual transfer through the Elgato to verify real-world behavior matches loopback tests.

**Phase mapping:** This is a meta-pitfall that applies to the entire refactoring effort. Address by making the *first* phase of the roadmap "add tests to the existing code without changing it," *then* begin structural changes.

**Confidence:** HIGH -- this is one of the most well-documented pitfalls in software engineering, and the current codebase has minimal test coverage (one loopback test with wrong function signatures).

---

## Minor Pitfalls

Mistakes that cause annoyance, confusion, or minor bugs.

---

### Pitfall 11: Existing Loopback Test is Already Broken

**What goes wrong:** The current `tests/test_loopback.py` calls `encode_frame(chunk, i)` with 2 arguments and `decode_frame(sampled)` expecting 3 return values, but the actual functions have different signatures:
- `encode_frame(data_chunk, frame_index, total_frames)` requires 3 arguments
- `decode_frame(frame_grid)` returns 4 values `(frame_index, total_frames, data, data_len)`

The test cannot run as-is. This means there is effectively zero test coverage.

**Prevention:** Fix the test signatures as the very first task. Then run it to establish the baseline before any refactoring.

**Phase mapping:** Immediate -- fix before any other work.

**Confidence:** HIGH -- directly observed by reading the code.

---

### Pitfall 12: Duplicated Constants Between Python and JavaScript

**What goes wrong:** Constants like `WIDTH`, `HEIGHT`, `BLOCK_SIZE`, `HEADER_LEN`, and PRNG parameters are defined independently in `common.py` and `sender.html`. If one is updated without the other, the sender and receiver will disagree on frame format, causing silent decoding failure.

**Prevention:**
1. Generate the JavaScript constants from the Python source (or vice versa) as part of a build step.
2. Or define constants in a shared JSON file that both Python and JavaScript read.
3. At minimum, document prominently that constants must match and add a test that parses both files and compares values.

**Phase mapping:** Address during architecture refactor.

**Confidence:** HIGH -- directly observed.

---

### Pitfall 13: Frame Capture Rate vs Display Rate Mismatch

**What goes wrong:** The sender displays frames at rate X, but the capture card captures at rate Y. If Y < X, frames are missed. If Y > X, duplicate frames are captured. The fountain code mode handles missed frames gracefully (that is its purpose), but duplicate frames waste decode effort. The sequential mode has no tolerance for missed frames at all -- a single miss corrupts the output.

In the current code, the sender defaults to `--fps 240` but the fountain receiver sets capture FPS to 60 (`cap.set(cv2.CAP_PROP_FPS, 60)` on line 177 of `receiver_fountain.py`). This 4:1 mismatch means the receiver sees only every ~4th frame in the best case.

**Prevention:**
1. Document that sender FPS should not exceed receiver capture FPS for sequential mode.
2. For fountain mode, this mismatch is acceptable but should be documented as expected behavior (fountain codes are designed for erasure channels).
3. Report actual capture FPS on the receiver side so users can tune sender FPS.
4. Consider auto-negotiation: sender embeds its FPS in the frame header, receiver reports if it is keeping up.

**Phase mapping:** Address during speed optimization phase.

**Confidence:** HIGH -- directly observed in the code.

---

### Pitfall 14: Python GIL and Byte-Level XOR Performance

**What goes wrong:** The fountain decoder performs XOR operations in a Python `for` loop (lines 69-70 and 103-104 of `receiver_fountain.py`): `for i in range(len(current_data)): current_data[i] ^= chunk_data[i]`. With `PAYLOAD_SIZE = 4044` bytes, this executes 4044 Python-level XOR operations per droplet. At 60 droplets/second, that is ~242,640 Python loop iterations/second just for XOR. This is orders of magnitude slower than necessary and becomes the bottleneck for decode speed.

**Prevention:**
1. Replace byte-level loops with NumPy vectorized XOR:
   ```python
   current_data = np.frombuffer(current_data, dtype=np.uint8)
   chunk_data = np.frombuffer(chunk_data, dtype=np.uint8)
   result = np.bitwise_xor(current_data, chunk_data).tobytes()
   ```
2. Or use Python's built-in `int.from_bytes()` / `int.to_bytes()` for whole-chunk XOR in a single operation.
3. For maximum performance, use `ctypes` or a C extension for the XOR hot loop.

**Phase mapping:** Address during speed optimization phase.

**Confidence:** HIGH -- directly observed in the code, and NumPy XOR performance is well-documented.

---

### Pitfall 15: OpenCV Color Space Conversion Uses BT.601 Instead of BT.709

**What goes wrong:** OpenCV's FFmpeg backend applies YUV-to-RGB conversion using the BT.601 matrix regardless of the stream's actual color standard. The Elgato 4K X outputs in BT.709 (the standard for HD content). This color matrix mismatch shifts pixel values by several units -- for 0/255 binary encoding with a threshold of 128 this is irrelevant, but for any future multi-level encoding (e.g., 4 gray levels at 0, 85, 170, 255), the BT.601/709 mismatch shifts the received values and can push them across threshold boundaries.

**Prevention:**
1. For binary encoding (0/255), this is a non-issue -- no action needed.
2. If implementing multi-level encoding, either:
   - Force the capture backend to deliver raw YUV and handle conversion manually
   - Calibrate thresholds based on actual received values rather than theoretical ones
   - Use the green channel only (closest to luma, least affected by color matrix choice)
3. Document this as a known limitation for future multi-bit encoding modes.

**Phase mapping:** Only relevant if/when implementing multi-bit encoding. Flag for future reference.

**Confidence:** MEDIUM -- the BT.601/709 mismatch is documented in OpenCV issue trackers, but its practical impact on binary encoding is negligible.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| **Testing foundation** | Existing test is broken (Pitfall 11) | Fix test signatures first, verify baseline before any changes |
| **Architecture refactor** | Breaking working prototype (Pitfall 10) | Incremental refactoring with loopback test gates between each step |
| **Architecture refactor** | Encoding mismatch confusion (Pitfall 3) | Unify frame format with magic number/version field |
| **Architecture refactor** | Bare exception handling (Pitfall 6) | Define error handling strategy before restructuring decode loop |
| **Encoding/decoding** | Chroma subsampling corruption (Pitfall 1) | Default to luma-only encoding; optional multi-bit as advanced mode |
| **Encoding/decoding** | MJPEG 8x8 alignment (Pitfall 2) | Use BLOCK_SIZE > 8 or multi-sample voting |
| **Fountain codes** | PRNG cross-language mismatch (Pitfall 4) | Test vector validation as first fountain-code test |
| **Fountain codes** | Degree distribution for small K (Pitfall 8) | Implement Robust Soliton or adaptive distribution |
| **Fountain codes** | XOR performance (Pitfall 14) | Replace Python loops with NumPy vectorized XOR |
| **Data integrity** | No checksums (Pitfall 9) | Add per-frame CRC-32 and whole-file SHA-256 |
| **Speed optimization** | waitKey FPS ceiling (Pitfall 5) | Alternative display backend or HTML sender for high-speed mode |
| **Speed optimization** | Sender/receiver FPS mismatch (Pitfall 13) | Document, auto-report actual FPS, match rates |
| **Cross-platform** | Windows-only APIs (Pitfall 7) | Platform abstraction layer, HTML sender as cross-platform path |
| **Multi-bit encoding** | BT.601/709 color shift (Pitfall 15) | Calibrate thresholds or use luma-only levels |
| **Ongoing** | Duplicated constants (Pitfall 12) | Shared config or build-step generation |

---

## Sources

### HIGH Confidence (Official Documentation / Direct Code Analysis)
- Elgato 4K X supported resolutions and formats: [Elgato Support](https://help.elgato.com/hc/en-us/articles/23479175821069-Elgato-Game-Capture-4K-X-Supported-Resolutions-and-Frame-Rates)
- OpenCV VideoCapture color conversion BT.601 bug: [OpenCV Issue #20513](https://github.com/opencv/opencv/issues/20513)
- OpenCV waitKey timing: [OpenCV Issue #23456](https://github.com/opencv/opencv/issues/23456)
- OpenCV VideoCapture backend overview: [OpenCV Docs](https://docs.opencv.org/3.4/d0/da7/videoio_overview.html)
- LT Codes original paper: [Michael Luby, Digital Fountain](https://www.inference.org.uk/mackay/dfountain/LT.pdf)
- Fountain codes overview: [CMU Course Notes](https://www.andrew.cmu.edu/user/gaurij/FountainCodes.pdf)
- MJPEG chroma subsampling: [NearStream Guide](https://www.nearstream.us/blog/the-science-of-color-chroma-subsampling-422-vs-420-capture-cards)
- Compression artifacts guide: [Encode.moe](https://guide.encode.moe/encoding/video-artifacts.html)

### MEDIUM Confidence (Verified with Multiple Sources)
- Pen Test Partners pixel exfiltration research: [PTP Blog](https://www.pentestpartners.com/security-blog/exfiltration-by-encoding-data-in-pixel-colour-values/)
- SplitMix32 PRNG implementations: [bryc/code on GitHub](https://github.com/bryc/code/blob/master/jshash/PRNGs.md)
- OBS capture card documentation: [OBS Forums](https://obsproject.com/forum/resources/capture-card-documentation-latency-decode-modes-formats-more.777/)
- NumPy XOR performance: [NumPy v2.3 Manual](https://numpy.org/doc/stable/reference/generated/numpy.bitwise_xor.html)
- Refactoring best practices: [Sonar](https://www.sonarsource.com/resources/library/refactoring/) and [Tembo](https://www.tembo.io/blog/code-refactoring)
- Testing hardware-dependent code: [SoftwareCraft](https://softwarecraft.ch/software-testing-when-hardware-is-involved/)

### LOW Confidence (Single Source / Needs Validation)
- OBS Rec.709 color space issue on macOS: [OBS Issue #11224](https://github.com/obsproject/obs-studio/issues/11224)
- Elgato RGB mode "not true RGB" claim from review: [Stream Guides](https://streamguides.gg/2024/02/elgato-4k-x-4k-pro-review/)
- Degree distribution optimization via RL: [arXiv:2502.07355](https://www.arxiv.org/pdf/2502.07355)
