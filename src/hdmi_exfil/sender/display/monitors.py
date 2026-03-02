"""Cross-platform monitor detection via screeninfo.

Replaces the Windows-only ``ctypes.windll.user32.EnumDisplayMonitors``
call in the original ``sender.py`` with a cross-platform implementation.

Falls back to a single 1920x1080 default monitor when ``screeninfo`` is
not installed or when detection fails at runtime (e.g. headless CI).

Usage::

    from hdmi_exfil.display.monitors import get_monitors
    monitors = get_monitors()
    # [{"left": 0, "top": 0, "right": 1920, "bottom": 1080, ...}, ...]
"""

from __future__ import annotations

_DEFAULT_MONITOR: dict[str, int] = {
    "left": 0,
    "top": 0,
    "right": 1920,
    "bottom": 1080,
    "width": 1920,
    "height": 1080,
}


def get_monitors() -> list[dict[str, int]]:
    """Return a list of monitor geometry dicts.

    Each dict has keys ``left``, ``top``, ``right``, ``bottom``,
    ``width``, ``height`` -- matching the format used by ``sender.py``.

    On failure (missing ``screeninfo``, headless server, etc.) a single
    default 1920x1080 monitor is returned.
    """
    try:
        from screeninfo import get_monitors as _si_get_monitors

        monitors: list[dict[str, int]] = []
        for m in _si_get_monitors():
            monitors.append(
                {
                    "left": m.x,
                    "top": m.y,
                    "right": m.x + m.width,
                    "bottom": m.y + m.height,
                    "width": m.width,
                    "height": m.height,
                }
            )
        if monitors:
            return monitors
    except (ImportError, RuntimeError, Exception):  # noqa: BLE001
        pass

    return [_DEFAULT_MONITOR.copy()]
