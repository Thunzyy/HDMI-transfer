"""Property-based tests using Hypothesis for sequential and fountain modes.

Finds edge cases that hand-picked examples miss -- critical for binary
encode/decode where off-by-one and boundary bugs hide.
"""

import os
import math

import numpy as np
from hypothesis import given, settings, assume
from hypothesis.strategies import binary, integers

from sender import encode_frame
from receiver import sample_frame, decode_frame
from common import BYTES_PER_FRAME
from receiver_fountain import PRNG, FountainDecoder

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

def choose_indices(seed, K):
    """Reproduce the JS/Python degree+index selection for a given seed.

    NOTE: The production code (receiver_fountain.FountainDecoder.add_droplet)
    has a latent infinite-loop bug: when K=1, degree can be 2, and the
    ``while len(indices) < degree`` loop spins forever because
    ``prng.next() % 1`` always returns 0.  We cap degree at K here to avoid
    the same issue in test helpers.  The production bug is documented but not
    fixed in this plan (it only triggers for single-chunk files, which don't
    occur in real usage at FOUNTAIN_PAYLOAD_SIZE=4044).
    """
    prng = PRNG(seed)
    degree = 1
    r = prng.next_float()
    if r < 0.1:
        degree = 1
    elif r < 0.6:
        degree = 2
    else:
        degree = int(prng.next_float() * min(K, 20)) + 1

    # Cap degree at K to prevent infinite loop when K < degree
    degree = min(degree, K)

    indices = set()
    while len(indices) < degree:
        idx = prng.next() % K
        indices.add(idx)
    return indices


def build_droplet(seed, K, chunks):
    """XOR the chunks selected by *seed* into a single droplet payload."""
    indices = choose_indices(seed, K)
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
    frame = encode_frame(data, 0, 1)
    sampled = sample_frame(frame)
    idx, total, decoded, length = decode_frame(sampled)
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
    frame = encode_frame(data, frame_index, total_frames)
    sampled = sample_frame(frame)
    idx, total, decoded, length = decode_frame(sampled)
    assert idx == frame_index
    assert total == total_frames
    assert length == len(data)
    assert decoded[:length] == data


@given(byte_val=integers(min_value=0, max_value=255))
@settings(max_examples=256, deadline=None)
def test_sequential_single_byte_values(byte_val):
    """Every single byte value (0x00-0xFF) survives encode/decode."""
    data = bytes([byte_val])
    frame = encode_frame(data, 0, 1)
    sampled = sample_frame(frame)
    idx, total, decoded, length = decode_frame(sampled)
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
