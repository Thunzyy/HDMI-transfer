"""Property-based tests using Hypothesis for sequential and fountain modes.

Finds edge cases that hand-picked examples miss -- critical for binary
encode/decode where off-by-one and boundary bugs hide.
"""

import os
import math

import numpy as np
from hypothesis import given, settings, assume
from hypothesis.strategies import binary, integers

from hdmi_transfer.core.protocols.sequential import SequentialProtocol
from hdmi_transfer.core.capture.sampler import sample_frame
from hdmi_transfer.core.config import BYTES_PER_FRAME, ROWS, COLS, BLOCK_SIZE
from hdmi_transfer.core.prng import PRNG, choose_indices
from hdmi_transfer.core.protocols.fountain import FountainDecoder

# Module-level protocol instance
_proto = SequentialProtocol()

# Fountain payload size for property tests. Smaller than the protocol constant
# (4044) to keep hypothesis runtimes manageable -- the FountainDecoder does
# byte-by-byte XOR in pure Python, so 4044-byte chunks * many examples is too
# slow. 256 bytes exercises the same codec logic (padding, XOR, peeling) while
# finishing in seconds rather than minutes.
FOUNTAIN_PAYLOAD_SIZE = 256


# ---------------------------------------------------------------------------
# Fountain test helpers (self-contained; duplicated from test_fountain.py to
# keep each test file independently runnable)
# ---------------------------------------------------------------------------

def _choose_indices_set(seed, K):
    """Wrapper returning set for compatibility with test helpers."""
    return set(choose_indices(seed, K))


def build_droplet(seed, K, chunks):
    """XOR the chunks selected by *seed* into a single droplet payload."""
    indices = _choose_indices_set(seed, K)
    size = len(chunks[0])
    payload = np.zeros(size, dtype=np.uint8)
    for idx in indices:
        payload ^= np.frombuffer(chunks[idx], dtype=np.uint8)
    return bytes(payload)


def prepare_chunks(data):
    """Split *data* into FOUNTAIN_PAYLOAD_SIZE chunks (pad last if needed)."""
    K = math.ceil(len(data) / FOUNTAIN_PAYLOAD_SIZE)
    chunks = []
    for i in range(K):
        start = i * FOUNTAIN_PAYLOAD_SIZE
        end = start + FOUNTAIN_PAYLOAD_SIZE
        chunk = data[start:end]
        if len(chunk) < FOUNTAIN_PAYLOAD_SIZE:
            chunk = chunk + b'\x00' * (FOUNTAIN_PAYLOAD_SIZE - len(chunk))
        chunks.append(bytearray(chunk))
    return K, chunks


# ---------------------------------------------------------------------------
# Sequential property-based tests
# ---------------------------------------------------------------------------

@given(data=binary(min_size=1, max_size=BYTES_PER_FRAME))
@settings(max_examples=200, deadline=None)
def test_sequential_roundtrip_any_data(data):
    """Arbitrary binary data of varying sizes survives encode/decode."""
    frame = _proto.encode_frame(data, 0, 1)
    sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
    idx, total, decoded, length = _proto.decode_frame_legacy(sampled)
    assert idx == 0
    assert total == 1
    assert length == len(data)
    assert decoded[:length] == data


@given(
    data=binary(min_size=1, max_size=BYTES_PER_FRAME),
    frame_index=integers(min_value=0, max_value=9999),
    total_frames=integers(min_value=1, max_value=10000),
)
@settings(max_examples=100, deadline=None)
def test_sequential_roundtrip_varying_index(data, frame_index, total_frames):
    """Random frame indices and totals survive encode/decode."""
    assume(frame_index < total_frames)
    frame = _proto.encode_frame(data, frame_index, total_frames)
    sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
    idx, total, decoded, length = _proto.decode_frame_legacy(sampled)
    assert idx == frame_index
    assert total == total_frames
    assert length == len(data)
    assert decoded[:length] == data


@given(byte_val=integers(min_value=0, max_value=255))
@settings(max_examples=256, deadline=None)
def test_sequential_single_byte_values(byte_val):
    """Every single byte value (0x00-0xFF) survives encode/decode."""
    data = bytes([byte_val])
    frame = _proto.encode_frame(data, 0, 1)
    sampled = sample_frame(frame, ROWS, COLS, BLOCK_SIZE)
    idx, total, decoded, length = _proto.decode_frame_legacy(sampled)
    assert length == 1
    assert decoded[0] == byte_val


# ---------------------------------------------------------------------------
# Fountain property-based tests
# ---------------------------------------------------------------------------

@given(data=binary(min_size=FOUNTAIN_PAYLOAD_SIZE + 1, max_size=FOUNTAIN_PAYLOAD_SIZE * 5))
@settings(max_examples=50, deadline=None)
def test_fountain_roundtrip_any_data(data):
    """Arbitrary binary data recovers through fountain encode/decode.

    Uses a smaller payload size (256 bytes) than production (4044) to keep
    hypothesis runtimes manageable. The fountain codec logic (padding, XOR,
    peeling) is exercised identically regardless of chunk size.

    min_size > FOUNTAIN_PAYLOAD_SIZE ensures K >= 2, avoiding a latent
    infinite-loop bug in FountainDecoder.add_droplet when K=1 and degree > 1.
    """
    K, chunks = prepare_chunks(data)
    decoder = FountainDecoder(K, FOUNTAIN_PAYLOAD_SIZE)
    seed = 1
    max_droplets = K * 10
    while not decoder.is_complete() and seed <= max_droplets:
        payload = build_droplet(seed, K, chunks)
        decoder.add_droplet(seed, payload)
        seed += 1
    assert decoder.is_complete(), (
        f"Failed to decode with K={K} after {seed - 1} droplets"
    )
    recovered = decoder.get_file_data()[:len(data)]
    assert recovered == bytearray(data)


@given(num_chunks=integers(min_value=2, max_value=5))
@settings(max_examples=20, deadline=None)
def test_fountain_roundtrip_exact_chunk_boundary(num_chunks):
    """Data that is an exact multiple of FOUNTAIN_PAYLOAD_SIZE recovers.

    num_chunks >= 2 avoids a latent infinite-loop bug in
    FountainDecoder.add_droplet when K=1 and degree > 1.
    """
    data = os.urandom(FOUNTAIN_PAYLOAD_SIZE * num_chunks)
    K, chunks = prepare_chunks(data)
    assert K == num_chunks
    decoder = FountainDecoder(K, FOUNTAIN_PAYLOAD_SIZE)
    seed = 1
    while not decoder.is_complete() and seed <= K * 10:
        payload = build_droplet(seed, K, chunks)
        decoder.add_droplet(seed, payload)
        seed += 1
    assert decoder.is_complete()
    recovered = decoder.get_file_data()[:len(data)]
    assert recovered == bytearray(data)
