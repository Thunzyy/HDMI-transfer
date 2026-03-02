---
phase: 07-monorepo-restructure
verified: 2026-03-02T21:30:00Z
status: passed
score: 12/12 must-haves verified
re_verification: false
---

# Phase 7: Monorepo Restructure Verification Report

**Phase Goal:** The codebase is reorganized into core/sender/receiver subpackages so sender and receiver can be installed independently with minimal dependencies
**Verified:** 2026-03-02T21:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                          | Status     | Evidence                                                                                      |
|----|--------------------------------------------------------------------------------|------------|-----------------------------------------------------------------------------------------------|
| 1  | cv2 is not imported in protocols/sequential.py                                 | VERIFIED   | No cv2 import found; np.repeat used at line 127-130                                           |
| 2  | cv2 is not imported in protocols/fountain.py                                   | VERIFIED   | No cv2 import found; np.repeat used at line 367                                               |
| 3  | cv2 is not imported in capture/sampler.py                                      | VERIFIED   | No cv2 import found; np.linspace + fancy indexing at lines 59-61                              |
| 4  | All existing tests pass after cv2.resize replacement                           | VERIFIED   | 170 passed excluding known pre-existing failures (test_fountain_decoder_with_numba, test_rsd_cross_language cross-platform issue) |
| 5  | Source tree has src/hdmi_exfil/core/, src/hdmi_exfil/sender/, src/hdmi_exfil/receiver/ directories | VERIFIED | All 11 subpackage directories confirmed present with __init__.py |
| 6  | Core contains only numpy/numba/stdlib dependencies — no cv2, pygame, or screeninfo imports | VERIFIED | grep scan of entire src/hdmi_exfil/core/ returned zero matches for cv2, pygame, screeninfo |
| 7  | Old import paths (hdmi_exfil.config, hdmi_exfil.protocols.sequential, etc.) still resolve via shims | VERIFIED | Python import test of all 10 public API paths returned "All old import paths resolve successfully" |
| 8  | All existing tests pass with zero import changes in test files                 | VERIFIED   | 170 passed; pre-existing failures unchanged from before restructure                           |
| 9  | pip install hdmi-exfil[sender] installs pygame-ce and screeninfo but NOT opencv-python | VERIFIED | Package metadata: pygame-ce and screeninfo gated on "sender" extra; opencv-python gated on "receiver" extra |
| 10 | pip install hdmi-exfil[receiver] installs opencv-python but NOT pygame-ce     | VERIFIED   | Package metadata confirms receiver extra contains only opencv-python                          |
| 11 | pip install hdmi-exfil[all] installs all dependencies                          | VERIFIED   | "all" extra defined as hdmi-exfil[sender] + hdmi-exfil[receiver]; dev extra confirmed working |
| 12 | hdmi-send, hdmi-recv, hdmi-calibrate, hdmi-bench entry points all resolve correctly | VERIFIED | def main() confirmed in all 4 canonical CLI files; shim modules chain correctly            |

**Score:** 12/12 truths verified

---

### Required Artifacts

#### Plan 07-01 Artifacts

| Artifact                                    | Expected                                      | Status     | Details                                                     |
|---------------------------------------------|-----------------------------------------------|------------|-------------------------------------------------------------|
| `src/hdmi_exfil/core/protocols/sequential.py` | Sequential protocol encoding without cv2    | VERIFIED   | No cv2 import; np.repeat at lines 127-130 with block_size  |
| `src/hdmi_exfil/core/protocols/fountain.py`   | Fountain protocol encoding without cv2      | VERIFIED   | No cv2 import; np.repeat at line 367 with block_size       |
| `src/hdmi_exfil/core/capture/sampler.py`      | Frame sampling without cv2 dependency       | VERIFIED   | np.linspace at lines 59-60; no cv2 import anywhere         |

#### Plan 07-02 Artifacts

| Artifact                                    | Expected                                      | Status     | Details                                                     |
|---------------------------------------------|-----------------------------------------------|------------|-------------------------------------------------------------|
| `src/hdmi_exfil/core/__init__.py`             | Core subpackage with re-exports             | VERIFIED   | Exists with docstring                                       |
| `src/hdmi_exfil/sender/__init__.py`           | Sender subpackage                           | VERIFIED   | Exists                                                      |
| `src/hdmi_exfil/receiver/__init__.py`         | Receiver subpackage                         | VERIFIED   | Exists                                                      |
| `src/hdmi_exfil/protocols/__init__.py`        | Backward-compatible shim at old import path | VERIFIED   | Contains "from hdmi_exfil.core.protocols import" at lines 2-3 |
| `src/hdmi_exfil/config.py`                   | Backward-compatible shim at old import path | VERIFIED   | Contains "from hdmi_exfil.core.config import *" at line 2  |

#### Plan 07-03 Artifacts

| Artifact       | Expected                                                          | Status   | Details                                                                  |
|----------------|-------------------------------------------------------------------|----------|--------------------------------------------------------------------------|
| `pyproject.toml` | Package config with sender/receiver/all extras and updated entry points | VERIFIED | optional-dependencies section present; sender/receiver/all/dev defined; core deps = numpy + numba only |

---

### Key Link Verification

| From                                        | To                                          | Via                              | Status   | Details                                                                     |
|---------------------------------------------|---------------------------------------------|----------------------------------|----------|-----------------------------------------------------------------------------|
| `src/hdmi_exfil/core/protocols/sequential.py` | numpy                                     | np.repeat for nearest-neighbor upscale | VERIFIED | `np.repeat(blocks_grid, self._profile.block_size, axis=0)` at line 128   |
| `src/hdmi_exfil/core/protocols/fountain.py`   | numpy                                     | np.repeat for nearest-neighbor upscale | VERIFIED | `np.repeat(blocks_grid, self._profile.block_size, axis=0)` at line 367   |
| `src/hdmi_exfil/protocols/__init__.py`        | `src/hdmi_exfil/core/protocols/__init__.py` | re-export shim                   | VERIFIED | `from hdmi_exfil.core.protocols import` at lines 2-3; runtime import confirmed |
| `src/hdmi_exfil/config.py`                   | `src/hdmi_exfil/core/config.py`             | re-export shim                   | VERIFIED | `from hdmi_exfil.core.config import *` at line 2                           |
| `src/hdmi_exfil/core/config.py`              | `src/hdmi_exfil/core/constants.json`        | importlib.resources.files        | VERIFIED | `files("hdmi_exfil.core").joinpath("constants.json")` at line 23           |
| `pyproject.toml`                             | `src/hdmi_exfil/cli/send.py`                | entry point hdmi-send            | VERIFIED | `hdmi-send = "hdmi_exfil.cli.send:main"` at line 34; shim chains to sender.cli.send |
| `pyproject.toml`                             | `src/hdmi_exfil/core/constants.json`        | package-data                     | VERIFIED | `"hdmi_exfil.core" = ["constants.json"]` at line 43                        |

---

### Requirements Coverage

| Requirement | Source Plan | Description                                                                                 | Status    | Evidence                                                                 |
|-------------|-------------|---------------------------------------------------------------------------------------------|-----------|--------------------------------------------------------------------------|
| STRUCT-01   | 07-02       | Code is organized into core/, sender/, receiver/ subpackages within src/hdmi_exfil/         | SATISFIED | All 11 subpackage directories confirmed; 57 Python files in correct locations |
| STRUCT-02   | 07-03       | User can install sender-only via `pip install hdmi-exfil[sender]` (pygame-ce, screeninfo)   | SATISFIED | Package metadata confirms sender extra; pygame-ce and screeninfo in [sender] only |
| STRUCT-03   | 07-03       | User can install receiver-only via `pip install hdmi-exfil[receiver]` (opencv-python)       | SATISFIED | Package metadata confirms receiver extra; opencv-python in [receiver] only |
| STRUCT-04   | 07-03       | User can install everything via `pip install hdmi-exfil` or `hdmi-exfil[all]`               | SATISFIED | [all] = [sender] + [receiver] confirmed in metadata; dev extra includes all |
| STRUCT-05   | 07-03       | Existing CLI commands (hdmi-send, hdmi-recv, hdmi-calibrate, hdmi-bench) work unchanged     | SATISFIED | All 4 entry points map to shim modules that chain to canonical main() functions |
| STRUCT-06   | 07-01       | cv2.resize in protocol encoding is replaced with np.repeat for clean core/sender dependency split | SATISFIED | Zero cv2 imports in sequential.py, fountain.py, sampler.py; np.repeat/linspace confirmed |
| STRUCT-07   | 07-03       | All existing tests pass after restructure (no regressions)                                  | SATISFIED | 170 tests pass; 2 pre-existing failures (numba JIT, Windows /dev/stdin) unchanged before and after |

All 7 requirements (STRUCT-01 through STRUCT-07) are accounted for across the three plans. No orphaned requirements found.

---

### Anti-Patterns Found

No anti-patterns detected.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | — | — | — |

Scanned: sequential.py, fountain.py, sampler.py, config.py, protocols/__init__.py, pyproject.toml for TODO/FIXME/PLACEHOLDER, empty returns, and stub patterns. Zero findings.

---

### Human Verification Required

#### 1. CLI command behavior

**Test:** Run `hdmi-send --help`, `hdmi-recv --help`, `hdmi-calibrate --help`, `hdmi-bench --help` on a system with the package installed
**Expected:** All four commands print usage/help without ImportError or ModuleNotFoundError
**Why human:** Entry point execution in a real shell requires an installed package; automated test coverage verifies import paths but not CLI subprocess invocation

#### 2. Selective install isolation

**Test:** In a fresh venv, run `pip install hdmi-exfil[sender]` then `python -c "import cv2"` (should fail), then `python -c "import pygame"` (should succeed)
**Expected:** pygame-ce available, opencv-python not installed
**Why human:** The current dev environment has all dependencies installed; isolation can only be verified in a clean venv

---

### Gaps Summary

No gaps found. All 12 observable truths are verified, all 7 requirements are satisfied, all key links are confirmed wired.

Pre-existing test failures noted in summaries (`test_fountain_decoder_with_numba` — Numba JIT assertion edge case; `test_rsd_cross_language` — Windows `/dev/stdin` path issue) are confirmed unrelated to this phase's changes and were present before any phase 7 work.

---

_Verified: 2026-03-02T21:30:00Z_
_Verifier: Claude (gsd-verifier)_
