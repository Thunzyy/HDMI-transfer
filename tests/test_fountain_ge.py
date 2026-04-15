"""Tests for Gaussian Elimination (GE) fallback in FountainDecoder.

When belief propagation (peeling) stalls -- no degree-1 droplets remain
and no stored droplet can be reduced to degree-1 -- GE operates in GF(2)
to solve the remaining system of linear equations and recover all chunks.

Test cases:
- GE recovers chunks when BP stalls (manually constructed scenario)
- GE round-trip for small K values (K=3, 5, 10, 20)
- GE not triggered when BP alone is sufficient
- GE gracefully fails when system is underdetermined
- GE interoperates with existing peeling (BP resolves some, GE finishes)
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from hdmi_transfer.prng import PRNG, choose_indices
from hdmi_transfer.protocols.degree import robust_soliton_cdf, sample_degree
from hdmi_transfer.protocols.fountain import FountainDecoder, PAYLOAD_SIZE


# ---- helpers ---------------------------------------------------------------

CHUNK_SIZE = 64  # small payloads keep tests fast


def _make_chunks(K: int, chunk_size: int = CHUNK_SIZE) -> list[np.ndarray]:
    """Create K random chunks as numpy uint8 arrays."""
    return [
        np.frombuffer(os.urandom(chunk_size), dtype=np.uint8).copy()
        for _ in range(K)
    ]


def _build_droplet_raw(
    indices: set[int],
    chunks: list[np.ndarray],
    chunk_size: int = CHUNK_SIZE,
) -> np.ndarray:
    """Build a droplet by XOR-ing the given chunk indices (raw, no PRNG)."""
    data = np.zeros(chunk_size, dtype=np.uint8)
    for idx in indices:
        data ^= chunks[idx]
    return data


def _build_droplet_from_seed(
    seed: int, K: int, chunks: list[np.ndarray], chunk_size: int = CHUNK_SIZE,
) -> bytes:
    """Build a droplet using the production PRNG+RSD path (matches add_droplet)."""
    prng = PRNG(seed)
    cdf = robust_soliton_cdf(K)
    degree = sample_degree(cdf, prng)
    degree = min(degree, K)
    indices: set[int] = set()
    while len(indices) < degree:
        idx = prng.next() % K
        indices.add(idx)
    data = np.zeros(chunk_size, dtype=np.uint8)
    for idx in indices:
        data ^= chunks[idx]
    return bytes(data)


# ---- test classes ----------------------------------------------------------


class TestGERecoveryWhenBPStalls:
    """GE fallback recovers chunks that BP cannot resolve."""

    def test_ge_recovers_when_bp_stalls(self):
        """Manually construct a scenario where BP stalls but GE can solve.

        Create K=5 chunks.  Feed the decoder:
        - Chunks 0 and 1 resolved by BP
        - 3 droplets covering {2,3}, {3,4}, {2,3,4} (linearly independent)

        After BP resolves chunks 0 and 1, the three droplets form a
        full-rank 3x3 GF(2) system over unknowns {2,3,4}.  BP cannot
        peel any of them (all degree >= 2), but GE solves the system.

        GF(2) matrix:     [1,1,0]   (eq0: c2^c3)
                          [0,1,1]   (eq1: c3^c4)
                          [1,1,1]   (eq2: c2^c3^c4)
        Rank = 3 (full rank).
        """
        K = 5
        chunks = _make_chunks(K)
        decoder = FountainDecoder(K, CHUNK_SIZE)

        # Degree-1 droplets for chunks 0 and 1 (BP resolves immediately)
        decoder.resolve_chunk(0, chunks[0].copy())
        decoder.resolve_chunk(1, chunks[1].copy())
        assert len(decoder.chunks) == 2  # BP resolved 0 and 1

        # Three droplets over unknowns {2,3,4} -- full rank in GF(2)
        d0 = _build_droplet_raw({2, 3}, chunks)
        d1 = _build_droplet_raw({3, 4}, chunks)
        d2 = _build_droplet_raw({2, 3, 4}, chunks)

        # Store these as unresolved droplets (simulating BP stall)
        for indices, data in [
            ({2, 3}, d0), ({3, 4}, d1), ({2, 3, 4}, d2),
        ]:
            entry = [set(indices), data.copy()]
            decoder.droplets.append(entry)
            for idx in indices:
                decoder.chunk_to_droplets[idx].append(entry)

        # BP is stalled: no degree-1 droplets
        assert not decoder.is_complete()
        assert len(decoder.chunks) == 2

        # GE should recover remaining chunks
        result = decoder.gaussian_elimination_fallback()
        assert result is True
        assert decoder.is_complete()

        # Verify data integrity
        for i in range(K):
            np.testing.assert_array_equal(decoder.chunks[i], chunks[i])

    def test_ge_recovers_k10_partial_bp(self):
        """K=10: BP resolves 7 chunks, GE recovers remaining 3."""
        K = 10
        chunks = _make_chunks(K)
        decoder = FountainDecoder(K, CHUNK_SIZE)

        # Resolve first 7 via direct injection (simulates BP success)
        for i in range(7):
            decoder.resolve_chunk(i, chunks[i].copy())
        assert len(decoder.chunks) == 7

        # 3 linearly independent equations over unknowns {7, 8, 9}:
        #   eq0: c7 XOR c8       -> [1,1,0]
        #   eq1: c8 XOR c9       -> [0,1,1]
        #   eq2: c7 XOR c8 XOR c9 -> [1,1,1]   (rank 3)
        eqs = [({7, 8}), ({8, 9}), ({7, 8, 9})]
        for indices in eqs:
            data = _build_droplet_raw(indices, chunks)
            entry = [set(indices), data.copy()]
            decoder.droplets.append(entry)
            for idx in indices:
                decoder.chunk_to_droplets[idx].append(entry)

        result = decoder.gaussian_elimination_fallback()
        assert result is True
        assert decoder.is_complete()

        for i in range(K):
            np.testing.assert_array_equal(decoder.chunks[i], chunks[i])


class TestGENotTriggeredWhenBPSufficient:
    """GE does not activate when BP alone completes decoding."""

    def test_ge_returns_false_when_complete(self):
        """When decoder is already complete, GE returns False (no work)."""
        K = 3
        chunks = _make_chunks(K)
        decoder = FountainDecoder(K, CHUNK_SIZE)

        # Resolve all chunks directly
        for i in range(K):
            decoder.resolve_chunk(i, chunks[i].copy())
        assert decoder.is_complete()

        # GE should have nothing to do
        result = decoder.gaussian_elimination_fallback()
        assert result is False

    def test_ge_no_overhead_when_bp_peels_all(self):
        """K=1: BP always resolves; GE never has unresolved droplets."""
        K = 1
        chunks = _make_chunks(K)
        decoder = FountainDecoder(K, CHUNK_SIZE)

        # Feed a degree-1 droplet (BP resolves immediately)
        decoder.add_droplet(1, bytes(chunks[0]))
        assert decoder.is_complete()

        # No unresolved droplets remain
        unresolved = [d for d in decoder.droplets if len(d[0]) > 0]
        assert len(unresolved) == 0


class TestGEInsufficientEquations:
    """GE gracefully fails when the system is underdetermined."""

    def test_ge_returns_false_underdetermined(self):
        """Fewer equations than unknowns: GE returns False."""
        K = 5
        chunks = _make_chunks(K)
        decoder = FountainDecoder(K, CHUNK_SIZE)

        # Resolve 2 chunks via BP
        decoder.resolve_chunk(0, chunks[0].copy())
        decoder.resolve_chunk(1, chunks[1].copy())

        # Only 1 equation for 3 unknowns (underdetermined)
        d0 = _build_droplet_raw({2, 3, 4}, chunks)
        entry = [{2, 3, 4}, d0.copy()]
        decoder.droplets.append(entry)
        for idx in {2, 3, 4}:
            decoder.chunk_to_droplets[idx].append(entry)

        result = decoder.gaussian_elimination_fallback()
        assert result is False
        assert not decoder.is_complete()

    def test_ge_returns_false_no_unresolved(self):
        """No unresolved droplets at all: GE returns False."""
        K = 3
        decoder = FountainDecoder(K, CHUNK_SIZE)
        # No chunks resolved, no droplets stored
        result = decoder.gaussian_elimination_fallback()
        assert result is False


class TestGERoundTripVariousK:
    """Parametrized round-trip test: encode, BP + GE, verify all K values."""

    @pytest.mark.parametrize("K", [3, 5, 10, 20])
    def test_ge_round_trip(self, K: int):
        """Full encode -> decode round-trip with BP+GE for K={K}.

        Uses production PRNG+RSD path.  After feeding enough droplets,
        the decoder (BP + GE fallback) must recover all chunks.
        """
        chunks = _make_chunks(K)
        decoder = FountainDecoder(K, CHUNK_SIZE)

        seed = 1
        max_droplets = K * 10  # generous budget

        while not decoder.is_complete() and seed <= max_droplets:
            droplet_data = _build_droplet_from_seed(seed, K, chunks, CHUNK_SIZE)
            decoder.add_droplet(seed, droplet_data)
            seed += 1

        assert decoder.is_complete(), (
            f"K={K}: decoder not complete after {seed - 1} droplets "
            f"(resolved {len(decoder.chunks)}/{K})"
        )

        for i in range(K):
            np.testing.assert_array_equal(
                decoder.chunks[i], chunks[i],
                err_msg=f"K={K}: chunk {i} data mismatch",
            )


class TestGETryAutoTrigger:
    """Verify try_gaussian_elimination is called from add_droplet."""

    def test_auto_trigger_after_bp_stall(self):
        """add_droplet calls GE automatically when BP stalls.

        Create K=5, inject degree-1 for chunks 0,1 via add_droplet,
        then inject crafted droplets that BP cannot peel (all degree>=2).
        After enough droplets, the auto-trigger should invoke GE
        and complete decoding.
        """
        K = 5
        chunks = _make_chunks(K)
        decoder = FountainDecoder(K, CHUNK_SIZE)

        # Resolve 0 and 1 directly (simulates earlier BP success)
        decoder.resolve_chunk(0, chunks[0].copy())
        decoder.resolve_chunk(1, chunks[1].copy())

        # Inject linearly independent droplets: {2,3}, {3,4}, {2,3,4}
        eqs = [({2, 3}), ({3, 4}), ({2, 3, 4})]
        for indices in eqs:
            data = _build_droplet_raw(indices, chunks)
            entry = [set(indices), data.copy()]
            decoder.droplets.append(entry)
            for idx in indices:
                decoder.chunk_to_droplets[idx].append(entry)

        # Feed one more droplet to trigger try_gaussian_elimination
        dummy_data = _build_droplet_from_seed(999, K, chunks, CHUNK_SIZE)
        decoder.add_droplet(999, dummy_data)

        # After auto-trigger, decoder should be complete (GE solved the rest)
        assert decoder.is_complete(), (
            f"Auto-trigger failed: resolved {len(decoder.chunks)}/{K}"
        )

        for i in range(K):
            np.testing.assert_array_equal(decoder.chunks[i], chunks[i])


class TestGEWithExistingTests:
    """Verify GE doesn't break existing fountain round-trip behaviour."""

    def test_existing_roundtrip_still_works(self):
        """Standard round-trip (K=10, production path) still completes."""
        K = 10
        chunk_size = PAYLOAD_SIZE  # use real payload size
        data = os.urandom(K * chunk_size)
        chunks_raw = [data[i * chunk_size:(i + 1) * chunk_size] for i in range(K)]
        chunks_np = [
            np.frombuffer(c, dtype=np.uint8).copy() for c in chunks_raw
        ]

        decoder = FountainDecoder(K, chunk_size)
        seed = 1
        max_droplets = K * 10

        while not decoder.is_complete() and seed <= max_droplets:
            droplet_data = _build_droplet_from_seed(
                seed, K, chunks_np, chunk_size,
            )
            decoder.add_droplet(seed, droplet_data)
            seed += 1

        assert decoder.is_complete(), (
            f"Round-trip failed: {len(decoder.chunks)}/{K} after {seed - 1} droplets"
        )

        recovered = decoder.get_file_data()
        assert bytes(recovered) == data


class TestGESafeguards:
    """Performance safeguards for GE fallback on large systems."""

    def test_try_ge_skips_for_large_total_k(self, monkeypatch):
        """GE auto-trigger is disabled for very large K to avoid stalls."""
        decoder = FountainDecoder(3000, CHUNK_SIZE)
        called = {"n": 0}

        def _fake_ge():
            called["n"] += 1
            return True

        monkeypatch.setattr(decoder, "gaussian_elimination_fallback", _fake_ge)
        decoder.try_gaussian_elimination()
        assert called["n"] == 0

    def test_try_ge_throttles_back_to_back_attempts(self, monkeypatch):
        """Consecutive GE auto-triggers are throttled by cooldown."""
        K = 80
        decoder = FountainDecoder(K, CHUNK_SIZE)
        called = {"n": 0}

        def _fake_ge():
            called["n"] += 1
            return True

        monkeypatch.setattr(decoder, "gaussian_elimination_fallback", _fake_ge)

        # Create a solvable-sized unresolved system (unknown=10, unresolved=10)
        for i in range(K):
            data = np.zeros(CHUNK_SIZE, dtype=np.uint8)
            entry = [{i}, data]
            decoder.droplets.append(entry)
            decoder.chunk_to_droplets[i].append(entry)

        decoder.try_gaussian_elimination()
        decoder.try_gaussian_elimination()

        assert called["n"] == 1
