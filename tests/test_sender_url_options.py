"""Exercise the real browser URL parser without a browser or HDMI hardware."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("query", "expected_fountain", "expected_sequential"),
    [
        ("", 1.5, 3),
        ("?fountainAutoStop=1", 1.5, 3),
        ("?fountainRedundancy=&sequentialRepeat=", 1.5, 3),
        ("?fountainRedundancy=%20&sequentialRedundancy=%20", 1.5, 3),
        ("?fountainRedundancy=invalid&sequentialRepeat=invalid", 1.5, 3),
        ("?fountainRedundancy=0", 0, 3),
        ("?fountainRedundancy=2.25&sequentialRepeat=4", 2.25, 4),
        ("?sequentialRedundancy=5", 1.5, 5),
        ("?sequentialRepeat=4&sequentialRedundancy=5", 1.5, 4),
    ],
)
def test_url_overrides_preserve_defaults_unless_a_number_is_supplied(
    query: str, expected_fountain: float, expected_sequential: int,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to run the browser URL parser")
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const parser = source.slice(source.indexOf('  function parseBoolParam('),
                            source.indexOf('  function resolveReceiverApiUrl('));
const config = {fountainRedundancy:1.5, sequentialRedundancy:3};
const scope = {URLSearchParams, window:{location:{search:process.argv[2]}},
               config, PROFILES:{}, runtimeOptions:{}};
vm.runInNewContext(parser + '\napplyUrlParams();', scope);
process.stdout.write(JSON.stringify(config));
"""
    result = subprocess.run(
        [node, "-e", script, str(ROOT / "src/interfaces/browser_sender/app.js"), query],
        capture_output=True, text=True, check=True, timeout=10,
    )
    config = json.loads(result.stdout)
    assert config["fountainRedundancy"] == expected_fountain
    assert config["sequentialRedundancy"] == expected_sequential
