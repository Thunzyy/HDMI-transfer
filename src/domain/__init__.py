"""Domain-level shared models and manifests."""

from hdmi_exfil.domain.models import (
    FOUNTAIN_HEADER_SIZE,
    SEQUENTIAL_HEADER_SIZE,
    FountainSpec,
    ProtocolManifest,
    ResolutionProfile,
    SequentialSpec,
)
from hdmi_exfil.domain.protocol_manifest import get_protocol_manifest

__all__ = [
    "FOUNTAIN_HEADER_SIZE",
    "SEQUENTIAL_HEADER_SIZE",
    "FountainSpec",
    "ProtocolManifest",
    "ResolutionProfile",
    "SequentialSpec",
    "get_protocol_manifest",
]
