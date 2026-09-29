from __future__ import annotations

import tomllib
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_uses_hdmi_transfer_distribution_name() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "hdmi-transfer"


def test_branding_uses_hdmi_transfer_in_readme_and_sender() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    sender = (REPO_ROOT / "sender.html").read_text(encoding="utf-8")

    assert re.search(r"(?m)^# HDMI Transfer\b|<h1\b[^>]*>\s*HDMI Transfer\b[^<]*</h1>", readme)
    assert "<title>HDMI Transfer" in sender


def test_repo_text_files_do_not_reference_old_project_name() -> None:
    forbidden = (
        "HDMI" + " Exfil",
        "HDMI" + "_exfil",
        "hdmi" + "_exfil",
        "hdmi" + "-exfil",
    )
    allowed_self = Path(__file__).resolve()
    roots = [
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "tools",
        REPO_ROOT / "docs",
        REPO_ROOT / "README.md",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "sender.html",
        REPO_ROOT / "hdmi_transfer",
    ]

    checked = 0
    for root in roots:
        if root.is_file():
            files = [root]
        elif root.exists():
            files = [p for p in root.rglob("*") if p.is_file()]
        else:
            continue
        for path in files:
            if path == allowed_self:
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pyc"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for old in forbidden:
                assert old not in text, f"{path} still contains legacy name: {old}"
            checked += 1

    assert checked > 0
