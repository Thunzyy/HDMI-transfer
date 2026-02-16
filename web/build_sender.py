"""Build sender.html from template + constants.json.

Reads ``constants.json`` from the installed ``hdmi_exfil`` package and
injects base values (WIDTH, HEIGHT, BLOCK_SIZE, FOUNTAIN_MAGIC) into
``sender.template.html``, producing the final ``sender.html``.

Usage::

    python web/build_sender.py                  # writes to project root
    python web/build_sender.py out/sender.html  # custom output path

Can also be imported::

    from web.build_sender import build
    build()
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def build(output_path: str | None = None) -> Path:
    """Generate ``sender.html`` from the template and constants.json.

    Parameters
    ----------
    output_path:
        Where to write the generated file.  Defaults to
        ``<project-root>/sender.html``.

    Returns
    -------
    Path
        Resolved path to the generated file.
    """
    # Locate constants.json from installed package
    from importlib.resources import files as _pkg_files

    constants_resource = _pkg_files("hdmi_exfil").joinpath("constants.json")
    constants = json.loads(constants_resource.read_text(encoding="utf-8"))

    # Locate template relative to this script
    script_dir = Path(__file__).resolve().parent
    template_path = script_dir / "sender.template.html"

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    template = template_path.read_text(encoding="utf-8")

    # Build replacement mapping
    # fountain_magic -> hex literal for JS (e.g. 61632 -> "0xF0C0")
    fountain_hex = "0x" + hex(constants["fountain_magic"])[2:].upper()

    replacements = {
        "{{CONST_WIDTH}}": str(constants["width"]),
        "{{CONST_HEIGHT}}": str(constants["height"]),
        "{{CONST_BLOCK_SIZE}}": str(constants["block_size"]),
        "{{CONST_FOUNTAIN_MAGIC}}": fountain_hex,
    }

    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    # Determine output path
    if output_path is None:
        # Default: project root / sender.html (one level up from web/)
        out = script_dir.parent / "sender.html"
    else:
        out = Path(output_path).resolve()

    out.write_text(result, encoding="utf-8")
    print(f"Generated {out} from template + constants.json")
    print(f"  WIDTH={constants['width']}, HEIGHT={constants['height']}, "
          f"BLOCK_SIZE={constants['block_size']}, "
          f"FOUNTAIN_MAGIC={fountain_hex}")

    return out


if __name__ == "__main__":
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None
    build(custom_path)
