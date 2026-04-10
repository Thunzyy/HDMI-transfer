from __future__ import annotations

from hdmi_exfil.domain.protocol_manifest import get_protocol_manifest


def test_protocol_manifest_exposes_profiles_and_headers() -> None:
    manifest = get_protocol_manifest()

    assert manifest.profiles["balanced"].width == 1920
    assert manifest.sequential.header_size == 17
    assert manifest.fountain.header_size == 16
