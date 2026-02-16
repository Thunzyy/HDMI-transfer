# Phase 5 Research: Fountain Code Optimization

## RESEARCH COMPLETE

## 1. Current State Analysis

### Degree Distribution (Ad-Hoc) — Duplicated in 4 Places

The same ad-hoc degree distribution is copy-pasted in:
1. `src/hdmi_exfil/prng.py:choose_indices()` (lines 39-70)
2. `src/hdmi_exfil/protocols/fountain.py:FountainDecoder.add_droplet()` (lines 70-81)
3. `src/hdmi_exfil/cli/send.py:_send_fountain()` (lines 243-252)
4. `web/sender.template.html:chooseIndices()` (lines 222-238) + generated `sender.html`

Current distribution:
```
r < 0.1  → degree = 1   (10%)
r < 0.6  → degree = 2   (50%)
else     → degree = random(1, min(K, 20)) + 1  (40%)
```

**Problems:**
- No theoretical basis — overhead is ~30%+ for typical K
- Degree cap at 20 is arbitrary (starves coverage for large K)
- Too few degree-1 droplets for reliable peeling start
- Too many degree-2 droplets (wastes encoding time)

### Current Decoder (Belief Propagation / Peeling)

`FountainDecoder` in `fountain.py` lines 47-139:
- **add_droplet()**: On-the-fly peeling — XOR out known chunks, resolve degree-1 immediately, store degree>1
- **resolve_chunk()**: Recursive propagation — when chunk resolved, propagate to all stored droplets referencing it
- **Storage**: `self.chunks: dict[int, np.ndarray]`, `self.droplets: list[list]`, `self.chunk_to_droplets: dict[int, list]`
- **XOR**: Uses Numba `xor_into()` (already JIT-compiled, releases GIL)

**Failure mode**: When no degree-1 droplets remain and no peeling is possible, decoder stalls. Must receive more droplets until a lucky degree-1 arrives. For small K, this can require 30%+ extra droplets.

### Header Format (Must Not Change)

```
FOUNT_HEADER_FMT: ">HIH"  → magic(2) + seed(4) + K(2) = 8 bytes pre-CRC
CRC32: 4 bytes
Total header: 12 bytes
PAYLOAD_SIZE: 12138 bytes (per frame)
```

The header has **no field for distribution parameters**. If we want to transmit c/delta/redundancy, we need to either:
- Encode them in the metadata (START chunk, chunk 0)
- Use fixed defaults (simplest — receiver always uses same c/delta)
- **Recommended**: Use fixed defaults; --redundancy controls sender-side only (how many extra droplets to send)

## 2. Robust Soliton Distribution (RSD)

### Mathematical Definition

**Step 1 — Ideal Soliton Distribution ρ(d):**
```
ρ(1) = 1/K
ρ(d) = 1/(d*(d-1))  for d = 2, ..., K
```

**Step 2 — Supplementary distribution τ(d):**
```
S = c * ln(K/δ) * √K  (expected ripple size)
pivot = floor(K/S)

τ(d) = (S/K) * (1/d)        for d = 1, 2, ..., pivot-1
τ(pivot) = (S/K) * ln(S/δ)  for d = pivot
τ(d) = 0                    for d > pivot
```

**Step 3 — Normalize:**
```
μ(d) = (ρ(d) + τ(d)) / Z
where Z = Σ(ρ(d) + τ(d)) for d=1..K
```

### Parameter Selection

| Parameter | Meaning | Recommended Range |
|-----------|---------|-------------------|
| `c` | Ripple size tuning | 0.03 - 0.5 (start with 0.1) |
| `δ` | Failure probability bound | 0.01 - 0.5 (start with 0.05) |
| `S` | Expected ripple size | Derived: `c * ln(K/δ) * √K` |

For K=100, c=0.1, δ=0.05: S ≈ 0.1 * ln(2000) * 10 ≈ 7.6

### Implementation Approach

Pre-compute CDF for a given (K, c, δ), then sample via binary search on CDF:
```python
def sample_degree(cdf, prng):
    r = prng.next_float()
    # Binary search in CDF for degree
    lo, hi = 1, len(cdf) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cdf[mid] < r:
            lo = mid + 1
        else:
            hi = mid
    return lo
```

**Critical constraint**: Sender and receiver MUST use the same (K, c, δ) to generate identical degree distributions from the same seed. Since the header only carries K, c and δ must be fixed constants (or derived from K deterministically).

### JS Sender Sync

The JavaScript `chooseIndices()` in `sender.template.html` must be updated to use the same RSD. Options:
1. Port the Python RSD to JavaScript (straightforward — same math)
2. Pre-compute CDF and embed it (impractical for variable K)
3. **Recommended**: Port the math — it's just basic arithmetic

## 3. Gaussian Elimination Fallback Decoder

### When BP Stalls

BP stalls when:
- No degree-1 droplets remain in the unresolved pool
- No stored droplet can be reduced to degree-1 via peeling
- Common for small K (K < 50) where the ripple dies quickly

### Hybrid BP + GE Approach

**On-the-fly Gaussian Elimination (OFG)**:
1. Run normal BP/peeling first (fast, O(n) per symbol)
2. When BP stalls AND decoder is not yet complete:
   - Build a matrix from unresolved droplets: rows = droplets, columns = unknown chunk indices
   - Apply Gaussian elimination to solve the system
   - Resolve any newly determined chunks → re-trigger BP propagation

**Implementation in current architecture**:

```python
def gaussian_elimination_fallback(self) -> bool:
    """Attempt GE on unresolved droplets when BP stalls."""
    # Collect unresolved droplets (indices, data pairs)
    unresolved = [(d[0].copy(), d[1]) for d in self.droplets if len(d[0]) > 0]
    if not unresolved:
        return False

    # Map unknown chunk indices to column indices
    unknown_chunks = sorted(set().union(*(d[0] for d in unresolved)))
    col_map = {chunk: i for i, chunk in enumerate(unknown_chunks)}
    n_unknowns = len(unknown_chunks)
    n_equations = len(unresolved)

    # Build binary matrix (GF(2)) and data vectors
    # Row reduce, back-substitute, resolve chunks
    ...
```

**Complexity**: O(n_unknowns^2 * n_equations) — acceptable for small K (<1000), which is our target range.

### GF(2) Matrix Operations

All XOR operations are in GF(2) (binary field). The matrix is sparse (most droplets have low degree from RSD). Options:
1. **Dense numpy boolean matrix**: Simple, fast for K < 1000 via numpy operations
2. **Sparse bitarray**: More memory-efficient but overkill for our K range
3. **Recommended**: Dense numpy uint8 matrix with XOR row operations

### When to Trigger GE

After each droplet is added via `add_droplet()`:
- If BP resolves it → normal path
- If BP doesn't resolve and `is_complete()` is False → check if we have enough unresolved equations (n_equations >= n_unknowns) → try GE
- **Optimization**: Don't try GE after every single droplet. Try when `len(droplets_unresolved) >= len(unknown_chunks)` (necessary condition for solvability)

## 4. Redundancy Parameter

### Sender-Side Only

`--redundancy 1.05` means: send `ceil(K * 1.05)` droplets then stop (or loop).

Current sender loops forever until ESC. Change to:
- If `--redundancy` specified: send exactly `ceil(K * redundancy)` droplets then pause/loop
- If not specified: loop forever (backward-compatible)

### Implementation Points

- CLI flag in `send.py` argparse: `--redundancy` (float, default=None)
- Same flag for JS sender: configurable in UI or URL param
- Receiver doesn't care — it just collects until complete

## 5. Synchronization Constraint (Critical)

The sender (Python or JS) and receiver (Python) must agree on the degree distribution for each (seed, K) pair. This is the **fundamental constraint** of this phase.

### Current Sync Points

| Component | Degree Logic Location | Must Update |
|-----------|----------------------|-------------|
| Python receiver (FountainDecoder.add_droplet) | `fountain.py:70-81` | Yes |
| Python sender (_send_fountain) | `send.py:243-252` | Yes |
| Python helper (choose_indices) | `prng.py:39-70` | Yes |
| JS sender (chooseIndices) | `sender.template.html:222-238` | Yes |
| Generated sender.html | `sender.html:222-238` | Rebuilt by build script |

### Sync Strategy

1. Create a single `degree_distribution.py` module with `compute_rsd_cdf(K, c, delta)` and `sample_degree(cdf, prng)`
2. Have all Python code import from this one module
3. Port the identical math to JS in `sender.template.html`
4. Write cross-language test vectors: for N seeds at various K values, verify Python and JS produce identical (degree, indices) pairs

## 6. File Touch Map

### New Files
- `src/hdmi_exfil/protocols/degree.py` — RSD computation, CDF, degree sampling (single source of truth)

### Modified Files
- `src/hdmi_exfil/protocols/fountain.py` — FountainDecoder: use RSD, add GE fallback
- `src/hdmi_exfil/prng.py` — Update choose_indices to use new degree module
- `src/hdmi_exfil/cli/send.py` — Use new degree module, add --redundancy flag
- `src/hdmi_exfil/cli/receive.py` — No changes needed (decoder handles it)
- `web/sender.template.html` — Port RSD to JavaScript
- `tests/test_fountain.py` — Update tests for new distribution, add GE tests, overhead benchmarks
- `tests/test_fountain_3bpp.py` — May need minor updates

### Unchanged Files
- `src/hdmi_exfil/protocols/base.py` — ABC unchanged
- `src/hdmi_exfil/protocols/xor_ops.py` — Numba XOR unchanged
- `src/hdmi_exfil/protocols/sequential.py` — Unrelated
- `src/hdmi_exfil/capture/` — Unrelated
- `src/hdmi_exfil/display/` — Unrelated
- Header format — No wire protocol changes needed

## 7. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| JS/Python RSD mismatch | Critical | Cross-language test vectors (mandatory) |
| GE too slow for large K | Medium | Only trigger when BP stalls; K<1000 is O(1M) ops max |
| RSD parameters wrong | Medium | Benchmark with K=10,100,1000; tune c/δ empirically |
| Existing tests break | Low | Old distribution replaced everywhere; tests updated to match |
| Numba incompatibility with new code | Low | GE uses numpy, not Numba; XOR ops unchanged |

## 8. Suggested Plan Breakdown

1. **Plan 05-01**: RSD degree distribution module + update Python choose_indices + cross-language vectors
2. **Plan 05-02**: Gaussian elimination fallback in FountainDecoder
3. **Plan 05-03**: Wire RSD into sender (Python + JS) + --redundancy CLI flag
4. **Plan 05-04**: Overhead benchmarks + parameter tuning + update tests
