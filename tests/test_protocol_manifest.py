from __future__ import annotations

from hdmi_transfer.core.protocols.fountain import (
    FOUNT_HEADER_CURRENT_PRE_CRC,
    FOUNT_MAGIC_V2,
)
from hdmi_transfer.domain.protocol_manifest import get_protocol_manifest


def test_protocol_manifest_exposes_profiles_and_headers() -> None:
    manifest = get_protocol_manifest()

    assert manifest.profiles["balanced"].width == 1920
    assert manifest.sequential.header_size == 17
    assert manifest.fountain.header_size == 16
    assert manifest.fountain.header_pre_crc == FOUNT_HEADER_CURRENT_PRE_CRC
    assert manifest.fountain.current_magic == FOUNT_MAGIC_V2
