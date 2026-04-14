"""Canonical manifest for protocol constants and built-in profiles."""

from __future__ import annotations

import json
import struct
from functools import lru_cache
from importlib.resources import files

from hdmi_exfil.domain.models import (
    FOUNTAIN_HEADER_SIZE,
    ProtocolManifest,
    ResolutionProfile,
    SequentialSpec,
    FountainSpec,
    SEQUENTIAL_HEADER_SIZE,
)

SEQ_HEADER_FMT = ">HBIIH"
SEQ_HEADER_PRE_CRC = struct.calcsize(SEQ_HEADER_FMT)
SEQ_CRC_SIZE = 4
FOUNTAIN_CRC_SIZE = 4
FOUNTAIN_HEADER_PRE_CRC = FOUNTAIN_HEADER_SIZE - FOUNTAIN_CRC_SIZE
FOUNTAIN_CURRENT_MAGIC_OFFSET = 1


@lru_cache(maxsize=1)
def get_protocol_manifest() -> ProtocolManifest:
    constants_path = files("hdmi_exfil.core").joinpath("constants.json")
    constants = json.loads(constants_path.read_text(encoding="utf-8"))

    profiles = {
        "speed": ResolutionProfile("speed", 1920, 1080, 8, 240),
        "balanced": ResolutionProfile("balanced", 1920, 1080, 8, 60),
        "quality": ResolutionProfile("quality", 3840, 2160, 8, 30),
    }

    return ProtocolManifest(
        width=constants["width"],
        height=constants["height"],
        block_size=constants["block_size"],
        threshold=constants["threshold"],
        profiles=profiles,
        sequential=SequentialSpec(
            magic=constants["seq_magic"],
            header_format=SEQ_HEADER_FMT,
            header_pre_crc=SEQ_HEADER_PRE_CRC,
            crc_size=SEQ_CRC_SIZE,
            header_size=SEQUENTIAL_HEADER_SIZE,
        ),
        fountain=FountainSpec(
            magic=constants["fountain_magic"],
            current_magic=(
                constants["fountain_magic"] + FOUNTAIN_CURRENT_MAGIC_OFFSET
            ) & 0xFFFF,
            header_pre_crc=FOUNTAIN_HEADER_PRE_CRC,
            header_size=FOUNTAIN_HEADER_SIZE,
        ),
    )
