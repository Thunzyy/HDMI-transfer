"""Build the standalone browser sender HTML from shared source assets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hdmi_transfer.interfaces.browser_sender import (
    render_protocol_javascript,
    render_sender_html,
)
_DEFAULT_PROTOCOL_OUTPUT = (
    _REPO_ROOT
    / "src"
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


def check_sender_assets(
    *,
    protocol_output: Path = _DEFAULT_PROTOCOL_OUTPUT,
    sender_output: Path = _DEFAULT_SENDER_OUTPUT,
) -> list[Path]:
    """Return generated assets that are missing or out of date."""
    expected_assets = {
        protocol_output: render_protocol_javascript(),
        sender_output: render_sender_html(),
    }
    stale_paths: list[Path] = []
    for path, expected in expected_assets.items():
        try:
            actual = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            stale_paths.append(path)
            continue
        if actual != expected:
            stale_paths.append(path)
    return stale_paths


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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check generated assets without rewriting them.",
    )
    args = parser.parse_args(argv)
    if args.check:
        stale_paths = check_sender_assets(
            protocol_output=args.protocol_output,
            sender_output=args.sender_output,
        )
        if stale_paths:
            for path in stale_paths:
                print(f"outdated generated asset: {path}")
            print("run `python tools/build_sender_html.py` to regenerate them")
            return 1
        print("browser sender assets are up to date")
        return 0
    build_sender_assets(
        protocol_output=args.protocol_output,
        sender_output=args.sender_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
