"""Protocol implementations for HDMI exfiltration encoding.

Exposes a protocol registry (``PROTOCOLS``) mapping protocol names to their
classes, and a convenience ``get_protocol`` factory function.  Both
``SequentialProtocol`` and ``FountainProtocol`` are registered automatically.
"""

from __future__ import annotations

from hdmi_exfil.protocols.base import EncodingProtocol, FrameResult
from hdmi_exfil.protocols.fountain import FountainDecoder, FountainProtocol
from hdmi_exfil.protocols.sequential import SequentialProtocol, TransferState

# ---------------------------------------------------------------------------
# Protocol registry -- maps canonical name -> protocol class
# ---------------------------------------------------------------------------

PROTOCOLS: dict[str, type[EncodingProtocol]] = {
    "sequential": SequentialProtocol,
    "fountain": FountainProtocol,
}


def get_protocol(name: str, **kwargs: object) -> EncodingProtocol:
    """Instantiate a protocol by *name*.

    Parameters
    ----------
    name:
        Protocol identifier (e.g. ``"sequential"``, ``"fountain"``).
    **kwargs:
        Forwarded to the protocol constructor.

    Raises
    ------
    ValueError
        If *name* is not a registered protocol.
    """
    cls = PROTOCOLS.get(name)
    if cls is None:
        available = ", ".join(sorted(PROTOCOLS))
        raise ValueError(
            f"Unknown protocol {name!r}. Available protocols: {available}"
        )
    return cls(**kwargs)


__all__ = [
    "EncodingProtocol",
    "FrameResult",
    "FountainDecoder",
    "FountainProtocol",
    "PROTOCOLS",
    "SequentialProtocol",
    "TransferState",
    "get_protocol",
]
