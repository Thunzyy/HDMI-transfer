# Phase 2: Protocol Foundation - Research

**Researched:** 2026-02-16
**Domain:** Binary frame protocol design -- magic numbers, CRC32 integrity, frame type system, SHA-256 file verification, dual-protocol routing
**Confidence:** HIGH

## Summary

This phase adds protocol-level intelligence to frames that are currently "dumb" byte containers. The existing codebase has zero frame synchronization (receiver blindly tries to decode every captured frame), zero integrity checking (corruption is silent), and no transfer lifecycle (no START/END signaling). Two encoding modes exist with fundamentally different bit densities (sequential 3bpp vs fountain 1bpp) and different header formats (12B vs 6B), but neither has magic numbers for identification.

The protocol changes are pure Python stdlib work: `struct` for binary packing, `zlib.crc32` for checksums, `hashlib.sha256` for file verification. No external libraries needed. The JavaScript sender (sender.html) must mirror the protocol changes -- CRC32 via an inline lookup table (50 lines), SHA-256 via the browser's native `crypto.subtle.digest()` API. All changes are backward-incompatible by design: the old format has no magic number, so mixed old/new frames are distinguishable.

The critical constraint is the byte budget. Sequential mode has 12150 raw bytes per frame; with the new 17-byte header (magic + type + index + total + data_len + CRC32), payload drops from 12138 to 12133 bytes -- a 5-byte reduction (0.04%). Fountain mode has 4050 raw bytes; with a new 12-byte header (magic + seed + K + CRC32), payload drops from 4044 to 4038 bytes -- a 6-byte reduction (0.15%). Both are negligible. The START frame metadata (file size, SHA-256 hash, filename) fits easily in a single frame's payload for both modes.

**Primary recommendation:** Implement protocol changes test-first -- write tests for the new header format, then modify encode/decode functions, then update existing tests. The protocol module should be a standalone set of functions (not a class hierarchy -- that is Phase 3's job). Keep all changes in the existing file structure (common.py, sender.py, receiver.py, receiver_fountain.py, sender.html).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| struct (stdlib) | -- | Binary packing/unpacking of frame headers | Already used, no alternative needed for fixed-format binary data |
| zlib (stdlib) | -- | CRC32 checksums via `zlib.crc32()` | Standard IEEE 802.3 CRC32, verified identical to JS implementations, built-in |
| hashlib (stdlib) | -- | SHA-256 file hashing via `hashlib.sha256()` | FIPS-certified, built-in, chunked update API for large files |
| crypto.subtle (Web API) | -- | SHA-256 in browser JavaScript via `digest('SHA-256', data)` | Native browser API, no dependencies, async but fast |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy (existing) | 2.3.5 | Array operations for encode/decode | Already used by production code, no change needed |
| pytest (existing) | 8.4.2 | Test runner | Already installed from Phase 1 |
| hypothesis (existing) | 6.151.6 | Property-based testing for protocol edge cases | Already installed from Phase 1 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| zlib.crc32 | crc32c (hardware-accelerated) | CRC32C uses a different polynomial; would not match standard CRC32 implementations in JS. Stick with standard IEEE 802.3 |
| Inline JS CRC32 table | SheetJS crc-32 CDN | sender.html is a standalone file with no external dependencies. Inline table (50 LOC) is preferable to CDN dependency |
| crypto.subtle.digest | JS CRC32 for file hash | SHA-256 provides stronger integrity guarantees; crypto.subtle is native and fast. CRC32 is insufficient for file-level verification |

**Installation:**
```bash
# No new packages needed -- all stdlib
# Existing test infrastructure from Phase 1 is sufficient
```

## Architecture Patterns

### Protocol Header Layouts

#### Sequential Protocol Header (17 bytes)
```
Offset  Size  Field         Format    Description
0       2     magic         >H        0xDA7A - sequential protocol identifier
2       1     frame_type    >B        0=IDLE, 1=START, 2=DATA, 3=END
3       4     frame_index   >I        Sequence number (0-based)
7       4     total_frames  >I        Total DATA frames in transfer
11      2     data_len      >H        Payload bytes in this frame (max 12133)
13      4     crc32         >I        CRC32 of header[0:13] + payload

Total header: 17 bytes
Struct format: '>HBIIH' (magic, type, index, total, data_len) = 13 bytes
CRC32 appended separately: 4 bytes
```

#### Fountain Protocol Header (12 bytes)
```
Offset  Size  Field         Format    Description
0       2     magic         >H        0xF0C0 - fountain protocol identifier
2       4     seed          >I        PRNG seed for this droplet
6       2     K             >H        Total source chunks
8       4     crc32         >I        CRC32 of header[0:8] + payload

Total header: 12 bytes
Struct format: '>HIH' (magic, seed, K) = 8 bytes
CRC32 appended separately: 4 bytes
```

### Frame Type System (Sequential Only)
```python
FRAME_TYPE_IDLE  = 0x00  # No data, receiver ignores
FRAME_TYPE_START = 0x01  # Transfer metadata (filename, size, SHA-256)
FRAME_TYPE_DATA  = 0x02  # File data payload
FRAME_TYPE_END   = 0x03  # Transfer complete signal
```

### START Frame Metadata Layout (in payload)
```
Offset  Size  Field         Format    Description
0       4     file_size     >I        Total file size in bytes (max 4GB)
4       32    sha256_hash   32s       SHA-256 digest of the original file
36      2     filename_len  >H        Length of filename in bytes
38      N     filename      Ns        UTF-8 encoded filename
```

### Byte Budget Summary
```
Sequential (3bpp):
  Raw capacity:  12150 bytes (97200 bits / 8)
  Old header:    12 bytes  -> payload: 12138 bytes
  New header:    17 bytes  -> payload: 12133 bytes
  Reduction:     5 bytes (0.04%)

Fountain (1bpp):
  Raw capacity:  4050 bytes (32400 bits / 8)
  Old header:    6 bytes   -> payload: 4044 bytes
  New header:    12 bytes  -> payload: 4038 bytes
  Reduction:     6 bytes (0.15%)
```

### Pattern 1: CRC32 Computation Scope
**What:** CRC32 covers the entire frame except the CRC field itself (header fields + payload)
**When to use:** Every frame encode/decode
**Why:** Protects header fields (magic, type, lengths) from corruption. A corrupted header with valid-looking payload is worse than detecting corruption early.
**Example:**
```python
import struct
import zlib

SEQ_MAGIC = 0xDA7A
SEQ_HEADER_FMT = '>HBIIH'  # magic, type, index, total, data_len
SEQ_HEADER_SIZE = struct.calcsize(SEQ_HEADER_FMT)  # 13 bytes
SEQ_CRC_SIZE = 4
SEQ_FULL_HEADER = SEQ_HEADER_SIZE + SEQ_CRC_SIZE  # 17 bytes

def encode_sequential_header(frame_type, frame_index, total_frames, data_chunk):
    """Build header + CRC for sequential protocol frame."""
    header = struct.pack(SEQ_HEADER_FMT,
        SEQ_MAGIC, frame_type, frame_index, total_frames, len(data_chunk))
    # CRC covers header fields + payload
    crc = zlib.crc32(header + data_chunk) & 0xFFFFFFFF
    return header + struct.pack('>I', crc) + data_chunk

def decode_sequential_header(frame_bytes):
    """Parse and verify sequential protocol frame. Returns None on failure."""
    if len(frame_bytes) < SEQ_FULL_HEADER:
        return None
    header = frame_bytes[:SEQ_HEADER_SIZE]
    magic, frame_type, frame_index, total_frames, data_len = \
        struct.unpack(SEQ_HEADER_FMT, header)
    if magic != SEQ_MAGIC:
        return None  # Not a sequential frame
    stored_crc = struct.unpack('>I', frame_bytes[SEQ_HEADER_SIZE:SEQ_FULL_HEADER])[0]
    payload = frame_bytes[SEQ_FULL_HEADER:SEQ_FULL_HEADER + data_len]
    # Verify CRC
    computed_crc = zlib.crc32(header + payload) & 0xFFFFFFFF
    if computed_crc != stored_crc:
        return None  # CRC mismatch -- corruption detected
    return frame_type, frame_index, total_frames, payload
```

### Pattern 2: Inline CRC32 for JavaScript (sender.html)
**What:** Table-based CRC32 using IEEE 802.3 polynomial, zero dependencies
**When to use:** sender.html for computing CRC32 of frame bytes before rendering
**Example:**
```javascript
// CRC32 lookup table (IEEE 802.3 polynomial 0xEDB88320)
const CRC32_TABLE = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  let crc = i;
  for (let j = 0; j < 8; j++) {
    crc = (crc & 1) ? ((crc >>> 1) ^ 0xEDB88320) : (crc >>> 1);
  }
  CRC32_TABLE[i] = crc >>> 0;
}

function crc32(bytes) {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) {
    crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}
```

### Pattern 3: SHA-256 in Browser JavaScript
**What:** Use native Web Crypto API for SHA-256 of file data before slicing into chunks
**When to use:** sender.html when a file is loaded, before transmission begins
**Example:**
```javascript
async function computeSHA256(uint8Array) {
  const hashBuffer = await crypto.subtle.digest('SHA-256', uint8Array);
  return new Uint8Array(hashBuffer);  // 32 bytes
}

// Usage in file load handler:
reader.onload = async () => {
  const raw = new Uint8Array(reader.result);
  const sha256Hash = await computeSHA256(raw);
  // sha256Hash is 32 bytes, embed in START frame metadata
};
```

### Pattern 4: Protocol Routing on Receiver
**What:** Read first 2 bytes of decoded frame to determine protocol, then route to correct decoder
**When to use:** Unified receiver that handles both sequential and fountain
**Example:**
```python
import struct

SEQ_MAGIC = 0xDA7A
FOUNTAIN_MAGIC = 0xF0C0

def route_frame(frame_bytes):
    """Determine protocol from magic number and route to correct decoder."""
    if len(frame_bytes) < 2:
        return None, None
    magic = struct.unpack('>H', frame_bytes[:2])[0]
    if magic == SEQ_MAGIC:
        return 'sequential', decode_sequential_frame(frame_bytes)
    elif magic == FOUNTAIN_MAGIC:
        return 'fountain', decode_fountain_frame(frame_bytes)
    else:
        return None, None  # Unknown/noise/idle
```

### Pattern 5: Transfer Lifecycle State Machine (Sequential)
**What:** Receiver tracks transfer state: IDLE -> RECEIVING (after START) -> COMPLETE (after END)
**When to use:** Sequential receiver main loop
**Example:**
```python
class TransferState:
    IDLE = 'idle'
    RECEIVING = 'receiving'
    COMPLETE = 'complete'
    ERROR = 'error'

state = TransferState.IDLE
expected_sha256 = None
file_size = None
filename = None
received_chunks = {}

# In main loop:
frame_type, index, total, payload = decode_frame(raw_bytes)

if frame_type == FRAME_TYPE_START and state == TransferState.IDLE:
    file_size, sha256_hash, filename = parse_start_metadata(payload)
    expected_sha256 = sha256_hash
    state = TransferState.RECEIVING

elif frame_type == FRAME_TYPE_DATA and state == TransferState.RECEIVING:
    received_chunks[index] = payload

elif frame_type == FRAME_TYPE_END and state == TransferState.RECEIVING:
    reassembled = reassemble(received_chunks)
    actual_sha256 = hashlib.sha256(reassembled).digest()
    if actual_sha256 != expected_sha256:
        state = TransferState.ERROR
        print("SHA-256 MISMATCH -- file corrupted")
    else:
        state = TransferState.COMPLETE
        save_file(filename, reassembled)
```

### Anti-Patterns to Avoid
- **Changing common.py HEADER_SIZE for both protocols:** Sequential and fountain have DIFFERENT header sizes. The common.py `HEADER_SIZE` should remain 17 (sequential) and fountain should define its own constant. Do NOT try to unify them.
- **Computing CRC on payload only:** Header corruption is just as dangerous. Always CRC the full frame (header + payload, excluding only the CRC field).
- **Embedding filename in the DATA payload stream:** The current approach mixes metadata into the data stream. Move filename/size/hash to the START frame. DATA frames carry only file content.
- **Creating a class hierarchy for protocols in this phase:** Phase 3 does architecture refactoring with ABCs. This phase should use simple functions to add protocol features to the existing code structure.
- **Breaking backward compatibility gradually:** Make the break clean and complete. Old frames have no magic number, new frames always have one. No "compatibility mode."

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CRC32 checksum | Custom polynomial implementation | `zlib.crc32()` (Python) / table-based lookup (JS) | Standard IEEE 802.3 polynomial, identical across Python and JS, battle-tested |
| SHA-256 hash | Custom hash function | `hashlib.sha256()` (Python) / `crypto.subtle.digest()` (JS) | Cryptographic hash functions are notoriously easy to get wrong; stdlib is FIPS-certified |
| Binary packing | Manual byte array manipulation | `struct.pack()`/`struct.unpack()` (Python) / `DataView` (JS) | Handles endianness, alignment, and format conversion correctly |
| Frame synchronization | Scanning for byte patterns in raw stream | Magic number at fixed offset after decode | The data is already grid-decoded; magic check is a simple 2-byte comparison at position 0 |

**Key insight:** Every component of this protocol uses Python stdlib or browser-native APIs. Zero external dependencies. The only "custom" code is the CRC32 lookup table in JavaScript (because sender.html has no imports), which is a well-known 15-line algorithm.

## Common Pitfalls

### Pitfall 1: CRC32 Signed vs Unsigned Confusion
**What goes wrong:** Python 3's `zlib.crc32()` returns an unsigned 32-bit integer, but JavaScript's bitwise operations produce signed 32-bit integers. Without `>>> 0` in JS, CRC values can be negative.
**Why it happens:** JavaScript has no unsigned 32-bit integer type. `^` and `>>>` coerce to 32-bit, but the sign bit interpretation differs.
**How to avoid:** Always use `>>> 0` in JavaScript to force unsigned interpretation. In Python, always mask with `& 0xFFFFFFFF` (though Python 3 already returns unsigned, the mask is a safety net).
**Warning signs:** CRC mismatches that only occur for certain data patterns (those producing CRC values with the high bit set).

### Pitfall 2: Endianness Mismatch Between Python and JavaScript
**What goes wrong:** Python `struct.pack('>I', value)` uses big-endian. JavaScript `DataView.setUint32(offset, value, false)` uses big-endian when the third parameter is `false`. If someone passes `true` (little-endian), all multi-byte fields will be garbled.
**Why it happens:** JavaScript DataView's `littleEndian` parameter defaults vary by developer habit.
**How to avoid:** Always explicitly pass `false` to all DataView methods for big-endian consistency. The existing codebase already uses `false` (big-endian) in sender.html's `view.setUint32(0, seed, false)`.
**Warning signs:** Magic numbers appearing byte-swapped (0x7ADA instead of 0xDA7A).

### Pitfall 3: Changing HEADER_SIZE Breaks BYTES_PER_FRAME Downstream
**What goes wrong:** `common.py` defines `BYTES_PER_FRAME = (BITS_PER_FRAME // 8) - HEADER_SIZE`. Changing `HEADER_SIZE` from 12 to 17 changes `BYTES_PER_FRAME` from 12138 to 12133. Every test and function using `BYTES_PER_FRAME` gets the new value automatically.
**Why it happens:** The constant is computed, not hardcoded.
**How to avoid:** This is actually correct behavior -- the tests auto-adjust. But be aware that fountain mode does NOT use `HEADER_SIZE` from common.py. Fountain constants are defined locally. The fountain HEADER_LEN must be updated separately (6 -> 12) in both sender.html and receiver_fountain.py.
**Warning signs:** Sequential tests pass but fountain tests fail, or vice versa.

### Pitfall 4: START Frame Sent as frame_index=0 Collides with DATA frame_index=0
**What goes wrong:** If START uses frame_index=0 and DATA frames also start at index 0, the receiver cannot distinguish them by index alone.
**Why it happens:** Not separating the index spaces for control frames and data frames.
**How to avoid:** START and END frames use a reserved index (e.g., 0xFFFFFFFF or simply ignored -- routing is by `frame_type`, not index). DATA frames use indices 0 through N-1. The frame_type field is the discriminator, not the index.
**Warning signs:** START frame payload overwritten by DATA frame 0.

### Pitfall 5: Forgetting to Update sender.html (JavaScript)
**What goes wrong:** Python sender/receiver gets the new protocol, but the JavaScript fountain sender still uses the old 6-byte header without magic or CRC. Receiver rejects all fountain frames as unknown protocol.
**Why it happens:** sender.html is a standalone HTML file with embedded JavaScript. It is easy to forget when modifying Python code.
**How to avoid:** Protocol changes must be applied to ALL senders/receivers simultaneously: sender.py, receiver.py, sender.html, receiver_fountain.py. Each plan should explicitly list which files are modified.
**Warning signs:** Fountain mode stops working entirely after protocol update.

### Pitfall 6: SHA-256 Computed Over Wrong Data
**What goes wrong:** Sender computes SHA-256 of `metadata_header + file_data` (with filename prefix) but receiver computes SHA-256 of just `file_data` after stripping the filename. Hashes never match.
**Why it happens:** The current code prepends filename metadata into the payload stream. With the new START frame carrying metadata separately, the SHA-256 must cover the raw file content only.
**How to avoid:** SHA-256 is computed over the raw file bytes BEFORE any protocol wrapping. Both sender and receiver agree on hashing the raw file content, not the protocol-wrapped version.
**Warning signs:** SHA-256 verification always fails even with perfect transmission.

### Pitfall 7: Fountain Mode Has No START/END Lifecycle
**What goes wrong:** Trying to add START/END frames to fountain mode. Fountain codes are rateless -- there is no "total_frames" and no natural "END" signal.
**Why it happens:** Assuming fountain mode needs the same lifecycle as sequential mode.
**How to avoid:** Fountain mode embeds metadata differently. The receiver detects completion when FountainDecoder.is_complete() returns True. File metadata (filename, size, SHA-256) can be embedded in the first few bytes of the reassembled data (as currently done), or in a special "metadata droplet" mechanism. For Phase 2, keep fountain metadata in-band (prepended to the data stream before chunking). The SHA-256 hash and filename are included in the data that gets fountain-encoded.
**Warning signs:** Trying to define FRAME_TYPE_START for fountain protocol.

## Code Examples

### Complete Sequential Frame Encode (Verified Algorithm)
```python
# Source: Designed from codebase analysis + zlib.crc32 verified on this system
import struct
import zlib

SEQ_MAGIC = 0xDA7A
FRAME_TYPE_IDLE = 0x00
FRAME_TYPE_START = 0x01
FRAME_TYPE_DATA = 0x02
FRAME_TYPE_END = 0x03

# Header format: magic(2) + type(1) + index(4) + total(4) + data_len(2) = 13
SEQ_HEADER_FMT = '>HBIIH'
SEQ_HEADER_PRE_CRC = struct.calcsize(SEQ_HEADER_FMT)  # 13
SEQ_CRC_SIZE = 4
SEQ_HEADER_SIZE = SEQ_HEADER_PRE_CRC + SEQ_CRC_SIZE  # 17

def build_sequential_frame(frame_type, frame_index, total_frames, payload):
    """Build a complete sequential protocol frame with CRC32."""
    header = struct.pack(SEQ_HEADER_FMT,
        SEQ_MAGIC, frame_type, frame_index, total_frames, len(payload))
    crc_data = header + payload
    crc = zlib.crc32(crc_data) & 0xFFFFFFFF
    return header + struct.pack('>I', crc) + payload

def parse_sequential_frame(frame_bytes):
    """Parse a sequential frame. Returns (type, index, total, payload) or None."""
    if len(frame_bytes) < SEQ_HEADER_SIZE:
        return None
    magic, ftype, index, total, dlen = struct.unpack(
        SEQ_HEADER_FMT, frame_bytes[:SEQ_HEADER_PRE_CRC])
    if magic != SEQ_MAGIC:
        return None
    stored_crc = struct.unpack('>I',
        frame_bytes[SEQ_HEADER_PRE_CRC:SEQ_HEADER_SIZE])[0]
    payload = frame_bytes[SEQ_HEADER_SIZE:SEQ_HEADER_SIZE + dlen]
    computed_crc = zlib.crc32(
        frame_bytes[:SEQ_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
    if computed_crc != stored_crc:
        return None  # Corruption detected
    return ftype, index, total, payload
```

### Complete Fountain Frame Encode (Verified Algorithm)
```python
# Source: Designed from codebase analysis
import struct
import zlib

FOUNTAIN_MAGIC = 0xF0C0

# Header format: magic(2) + seed(4) + K(2) = 8
FOUNT_HEADER_FMT = '>HIH'
FOUNT_HEADER_PRE_CRC = struct.calcsize(FOUNT_HEADER_FMT)  # 8
FOUNT_CRC_SIZE = 4
FOUNT_HEADER_SIZE = FOUNT_HEADER_PRE_CRC + FOUNT_CRC_SIZE  # 12

def build_fountain_frame(seed, K, payload):
    """Build a complete fountain protocol frame with CRC32."""
    header = struct.pack(FOUNT_HEADER_FMT, FOUNTAIN_MAGIC, seed, K)
    crc_data = header + payload
    crc = zlib.crc32(crc_data) & 0xFFFFFFFF
    return header + struct.pack('>I', crc) + payload

def parse_fountain_frame(frame_bytes):
    """Parse a fountain frame. Returns (seed, K, payload) or None."""
    if len(frame_bytes) < FOUNT_HEADER_SIZE:
        return None
    magic, seed, K = struct.unpack(
        FOUNT_HEADER_FMT, frame_bytes[:FOUNT_HEADER_PRE_CRC])
    if magic != FOUNTAIN_MAGIC:
        return None
    stored_crc = struct.unpack('>I',
        frame_bytes[FOUNT_HEADER_PRE_CRC:FOUNT_HEADER_SIZE])[0]
    payload = frame_bytes[FOUNT_HEADER_SIZE:]
    computed_crc = zlib.crc32(
        frame_bytes[:FOUNT_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
    if computed_crc != stored_crc:
        return None  # Corruption detected
    return seed, K, payload
```

### START Frame Metadata Packing
```python
import hashlib
import struct

def build_start_metadata(filename, file_data):
    """Build START frame payload with file metadata."""
    sha256_hash = hashlib.sha256(file_data).digest()  # 32 bytes
    filename_bytes = filename.encode('utf-8')
    metadata = struct.pack('>I', len(file_data))  # 4B file_size
    metadata += sha256_hash                         # 32B SHA-256
    metadata += struct.pack('>H', len(filename_bytes))  # 2B filename_len
    metadata += filename_bytes                      # NB filename
    return metadata

def parse_start_metadata(payload):
    """Parse START frame payload. Returns (file_size, sha256, filename)."""
    file_size = struct.unpack('>I', payload[0:4])[0]
    sha256_hash = payload[4:36]
    filename_len = struct.unpack('>H', payload[36:38])[0]
    filename = payload[38:38 + filename_len].decode('utf-8')
    return file_size, sha256_hash, filename
```

### CRC32 Cross-Language Verification Test
```python
import zlib

def test_crc32_known_vectors():
    """Verify Python CRC32 matches known IEEE 802.3 test vectors."""
    assert zlib.crc32(b'') & 0xFFFFFFFF == 0x00000000
    assert zlib.crc32(b'123456789') & 0xFFFFFFFF == 0xCBF43926
    # These same values must be produced by the JS implementation
```

### JavaScript CRC32 + Protocol Header (for sender.html)
```javascript
// CRC32 lookup table generation (one-time, at script load)
const CRC32_TABLE = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  let c = i;
  for (let j = 0; j < 8; j++) {
    c = (c & 1) ? ((c >>> 1) ^ 0xEDB88320) : (c >>> 1);
  }
  CRC32_TABLE[i] = c >>> 0;
}

function crc32(bytes) {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) {
    crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

// Build fountain frame with protocol header
function buildProtocolFrame(seed, K, payload) {
  const HEADER_LEN = 12;  // magic(2) + seed(4) + K(2) + crc(4)
  const frame = new Uint8Array(HEADER_LEN + payload.length);
  const view = new DataView(frame.buffer);

  // Header fields (big-endian)
  view.setUint16(0, 0xF0C0, false);   // magic
  view.setUint32(2, seed, false);       // seed
  view.setUint16(6, K, false);          // K

  // Copy payload
  frame.set(payload, HEADER_LEN);

  // Compute CRC over header[0:8] + payload
  const crcData = new Uint8Array(8 + payload.length);
  crcData.set(frame.subarray(0, 8));
  crcData.set(payload, 8);
  const crcValue = crc32(crcData);
  view.setUint32(8, crcValue, false);   // CRC32

  return frame;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No frame sync -- decode every frame | Magic number check (2 bytes) at frame start | This phase | Receiver ignores noise/idle, only processes valid protocol frames |
| No integrity check | Per-frame CRC32 over header+payload | This phase | Immediate corruption detection, corrupted frames flagged not silently accepted |
| No file verification | SHA-256 embedded in START frame, verified after reassembly | This phase | End-to-end file integrity guarantee |
| Filename embedded in payload stream | Filename in START frame metadata | This phase | Clean separation of metadata and data; no parsing ambiguity |
| Single undifferentiated frame format | Magic number routing (0xDA7A vs 0xF0C0) | This phase | Unified receiver can handle both protocols |
| No transfer lifecycle | START/DATA/END frame types | This phase | Receiver knows when transfer begins and ends |

**Deprecated/outdated:**
- The old 12-byte header format (frame_index + total_frames + data_len, no magic) is replaced entirely
- The old 6-byte fountain header (seed + K, no magic) is replaced entirely
- Filename prepended to payload data stream is replaced by START frame metadata

## Codebase-Specific Design Decisions

### Decision 1: Where CRC32 Is Computed in the Pipeline
The encode/decode pipeline is: raw bytes -> struct.pack header -> numpy bit conversion -> pixel rendering -> capture -> pixel sampling -> numpy bit conversion -> struct.unpack header -> raw bytes. CRC32 is computed BEFORE bit conversion (on the packed bytes) and verified AFTER bit conversion (on the unpacked bytes). This means CRC detects corruption from the entire optical channel (encoding, display, capture, decoding, thresholding).

### Decision 2: Fountain Mode Metadata Strategy
Fountain mode does not have START/END frames. File metadata (filename, file_size, SHA-256) remains prepended to the data stream before chunking, as it currently is. The fountain receiver reconstructs all chunks, concatenates them, then parses the metadata prefix. SHA-256 verification happens after full reassembly, comparing against the hash extracted from the metadata prefix.

This means fountain mode metadata format is:
```
[4B file_size][32B SHA-256][2B filename_len][NB filename][file_content]
```

This is slightly different from the current format which is:
```
[4B filename_len][NB filename][file_content]
```

The addition of file_size and SHA-256 to the fountain metadata prefix is a clean extension of the existing approach.

### Decision 3: common.py Changes
- `HEADER_SIZE` changes from 12 to 17 (sequential header with CRC)
- `BYTES_PER_FRAME` auto-recalculates to 12133 (was 12138)
- New constants added: `SEQ_MAGIC`, `FOUNTAIN_MAGIC`, frame type constants
- Fountain-specific constants remain local to fountain files (not in common.py) -- this is consistent with the current design

### Decision 4: Test Update Strategy
All Phase 1 tests that use `encode_frame`/`decode_frame` must be updated because:
1. `encode_frame` will pack the new header format (magic, type, CRC)
2. `decode_frame` will verify magic and CRC, rejecting frames that fail
3. `BYTES_PER_FRAME` will change from 12138 to 12133 (auto via common.py)

Tests that only use `PRNG`/`FountainDecoder` directly (test_prng.py, fountain-specific parts of test_fountain.py) will NOT break.

### Decision 5: Existing Tests are Updated, Not Replaced
The Phase 1 tests remain valid -- they test the same encode/decode round-trip logic. They just need to account for the new header format. The test structure and assertions stay the same; only the internal protocol bytes change (transparently, since tests call `encode_frame`/`decode_frame` which handle the format).

## Impact on Existing Files

| File | Changes Required | Risk |
|------|-----------------|------|
| common.py | HEADER_SIZE 12->17, add protocol constants (magic numbers, frame types) | LOW -- simple constant changes |
| sender.py | encode_frame builds new header format, new build_start_frame function | MEDIUM -- core encoding function changes |
| receiver.py | decode_frame checks magic+CRC, new transfer lifecycle state machine | MEDIUM -- core decoding + new state logic |
| sender.html | New 12B fountain header, CRC32 table+function, SHA-256 via crypto.subtle | MEDIUM -- JS changes must exactly match Python |
| receiver_fountain.py | New 12B fountain header parsing with magic+CRC, enhanced metadata | MEDIUM -- header format change + metadata extension |
| tests/test_sequential.py | Update to use new encode_frame API (frame_type parameter) | LOW -- transparent if API stays compatible |
| tests/test_loopback.py | Same as test_sequential.py | LOW |
| tests/test_fountain.py | No changes needed (tests PRNG/decoder directly) | NONE |
| tests/test_properties.py | Sequential tests update, fountain tests unchanged | LOW |

## Open Questions

1. **Should encode_frame API remain backward-compatible?**
   - What we know: Current signature is `encode_frame(data_chunk, frame_index, total_frames)`. Adding frame_type as a parameter changes the API.
   - What's unclear: Whether to add frame_type as a new parameter or make it internal (always DATA for the main encode function).
   - Recommendation: Add `frame_type` parameter with default `FRAME_TYPE_DATA` so existing callers work unchanged. Add separate `encode_start_frame()` and `encode_end_frame()` convenience functions. Tests can call `encode_frame(data, 0, 1)` and it works transparently with new header.

2. **chooseIndices infinite-loop bug -- fix now or Phase 5?**
   - What we know: The context says "must fix in Phase 2 or Phase 5." It affects sender.html and receiver_fountain.py. The bug triggers when degree > K.
   - What's unclear: Whether fixing it changes the protocol (it does -- different degree capping means different indices for some seeds).
   - Recommendation: Fix in this phase since we are already modifying both sender.html and receiver_fountain.py for protocol headers. The fix is a single line: `degree = Math.min(degree, K)` in JS and `degree = min(degree, K)` in Python. Fixing now while touching these files minimizes risk.

3. **Fountain metadata format change -- will it break test_fountain.py tests?**
   - What we know: test_fountain.py tests the FountainDecoder directly with raw payloads, not with metadata. The metadata change (adding file_size + SHA-256 prefix) only affects the wrapping layer.
   - What's unclear: Whether any test relies on the current `[4B name_len][name][content]` format.
   - Recommendation: test_fountain.py is safe -- it operates below the metadata layer. New tests for the metadata format should be added.

## Sources

### Primary (HIGH confidence)
- **Python zlib.crc32 documentation** -- [docs.python.org/3/library/zlib.html](https://docs.python.org/3/library/zlib.html) -- CRC32 API verified on this system
- **Python struct documentation** -- [docs.python.org/3/library/struct.html](https://docs.python.org/3/library/struct.html) -- format strings and byte order
- **Python hashlib documentation** -- [docs.python.org/3/library/hashlib.html](https://docs.python.org/3/library/hashlib.html) -- SHA-256 API
- **MDN SubtleCrypto.digest()** -- [developer.mozilla.org](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/digest) -- Browser SHA-256 API
- **Direct codebase analysis** -- All source files read, byte budgets computed, function signatures verified
- **CRC32 test vector verification** -- `zlib.crc32(b'123456789') == 0xCBF43926` confirmed on this system (IEEE 802.3 standard)

### Secondary (MEDIUM confidence)
- **CRC32 scope best practice** -- [Wikipedia CRC-based framing](https://en.wikipedia.org/wiki/CRC-based_framing), [Serial Programming/Forming Data Packets](https://en.wikibooks.org/wiki/Serial_Programming/Forming_Data_Packets) -- CRC should cover header+payload
- **JS CRC32 implementation** -- [SimplyCalc CRC-32 Source](https://simplycalc.com/crc32-source.php), [SheetJS/js-crc32](https://github.com/SheetJS/js-crc32) -- table-based IEEE 802.3 polynomial

### Tertiary (LOW confidence)
- None -- all findings verified through stdlib documentation or direct execution

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all tools are Python stdlib or browser-native APIs, verified on this system
- Architecture: HIGH -- byte budgets computed exactly, header layouts designed with verified struct format sizes
- Pitfalls: HIGH -- identified from direct codebase analysis and cross-language compatibility testing in Phase 1
- Code examples: HIGH -- based on verified `zlib.crc32`, `struct.pack`, and `hashlib.sha256` behavior on this system

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (stable domain -- stdlib APIs do not change between Python versions)
