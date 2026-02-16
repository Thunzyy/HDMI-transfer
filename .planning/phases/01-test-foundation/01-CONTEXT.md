# Phase 1: Test Foundation - Context

**Gathered:** 2026-02-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish automated test safety net around the existing working prototype. Unit tests for encode/decode, PRNG cross-language verification, loopback hardware tests, and property-based fuzzing. No code changes to the production modules — only add tests and fix the broken test file.

</domain>

<decisions>
## Implementation Decisions

### PRNG Verification
- Claude's discretion on approach: static JSON test vectors vs Node.js subprocess vs other method
- Claude analyzes the `(self.a | 0)` no-op in Python PRNG and determines correct fix — must match JS output exactly
- Claude determines sufficient seed/output coverage for test vectors
- Claude decides whether to also verify `chooseIndices()` end-to-end or just raw PRNG output

### Pass/Fail Criteria
- Phase 2 gate: core tests must be green (unit tests + PRNG vectors)
- Loopback/hardware tests can be skipped if Elgato not available — they are NOT a gate for Phase 2
- Hardware tests should be marked so they can be excluded when Elgato is not plugged in
- User sometimes works without hardware — tests must be useful without Elgato

### Baseline
- Tag current working prototype as `v0.1-working-prototype` BEFORE any changes
- This is the rollback point if tests reveal issues

### Claude's Discretion
- Test data strategy (file sizes, edge cases, binary vs text)
- Test runner setup (pytest markers, command structure)
- PRNG verification approach (static vectors vs runtime generation)
- PRNG seed/output coverage depth
- Whether chooseIndices needs separate verification
- Property-based test parameters (hypothesis settings)

</decisions>

<specifics>
## Specific Ideas

- User works on multiple machines, not all have Elgato — hardware tests must be skippable
- Research flagged: existing test_loopback.py has wrong function signatures — fix is first priority
- Research flagged: Python PRNG has meaningless `(self.a | 0)` copied from JS — needs analysis

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-test-foundation*
*Context gathered: 2026-02-16*
