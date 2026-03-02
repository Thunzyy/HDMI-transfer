"""Backward-compatible re-export -- canonical location: hdmi_exfil.core.protocols."""
from hdmi_exfil.core.protocols import *  # noqa: F401,F403
from hdmi_exfil.core.protocols import (  # noqa: F401
    EncodingProtocol,
    FrameResult,
    FountainDecoder,
    FountainProtocol,
    PROTOCOLS,
    SequentialProtocol,
    TransferState,
    get_protocol,
    __all__,
)
