from __future__ import annotations

from pathlib import Path


def test_quality_gate_script_lists_required_checks() -> None:
    text = Path("tools/run_quality_gate.ps1").read_text(encoding="utf-8")

    assert "pytest" in text
    assert "tests/test_fountain_overhead.py" in text
    assert "tests/perf/test_fountain_budget.py" in text
    assert "tools/build_sender_html.py" in text


def test_ci_workflow_references_quality_gate_script() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "tools/run_quality_gate.ps1" in text
    assert "-SkipNativeLoopback" not in text
