"""Build the standalone browser sender HTML from shared source assets."""

from __future__ import annotations

import argparse
from pathlib import Path

from hdmi_exfil.interfaces.browser_sender import (
    render_protocol_javascript,
    render_sender_html,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PROTOCOL_OUTPUT = (
    _REPO_ROOT
    / "src"
    / "hdmi_exfil"
    / "interfaces"
    / "browser_sender"
    / "protocol.generated.js"
)
_DEFAULT_SENDER_OUTPUT = _REPO_ROOT / "sender.html"


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def build_protocol_javascript(output_path: Path = _DEFAULT_PROTOCOL_OUTPUT) -> Path:
    """Write the generated protocol constants module."""
    return _write_text(output_path, render_protocol_javascript())


def build_sender_html(output_path: Path = _DEFAULT_SENDER_OUTPUT) -> Path:
    """Write the standalone sender HTML."""
    return _write_text(output_path, render_sender_html())


def build_sender_assets(
    *,
    protocol_output: Path = _DEFAULT_PROTOCOL_OUTPUT,
    sender_output: Path = _DEFAULT_SENDER_OUTPUT,
) -> tuple[Path, Path]:
    """Write all generated browser sender assets."""
    protocol_path = build_protocol_javascript(protocol_output)
    sender_path = build_sender_html(sender_output)
    return protocol_path, sender_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the standalone browser sender HTML and protocol assets.",
    )
    parser.add_argument(
        "--sender-output",
        type=Path,
        default=_DEFAULT_SENDER_OUTPUT,
        help="Output path for the standalone sender HTML.",
    )
    parser.add_argument(
        "--protocol-output",
        type=Path,
        default=_DEFAULT_PROTOCOL_OUTPUT,
        help="Output path for the generated protocol JavaScript module.",
    )
    args = parser.parse_args(argv)
    build_sender_assets(
        protocol_output=args.protocol_output,
        sender_output=args.sender_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
