"""Helpers for explicit backward-compatible re-export modules."""

from __future__ import annotations

import os
import warnings
from importlib import import_module
from types import ModuleType
from typing import Any

COMPAT_TARGET_ATTR = "__compat_target__"
COMPAT_WARNING_ENV = "HDMI_EXFIL_WARN_LEGACY_IMPORTS"

_WARN_TRUE_VALUES = {"1", "true", "yes", "on"}
_warned_imports: set[tuple[str, str]] = set()


def _should_warn() -> bool:
    value = os.environ.get(COMPAT_WARNING_ENV, "")
    return value.strip().lower() in _WARN_TRUE_VALUES


def _warn_once(*, legacy_module: str, target_module: str) -> None:
    if not _should_warn():
        return

    key = (legacy_module, target_module)
    if key in _warned_imports:
        return
    _warned_imports.add(key)

    warnings.warn(
        f"{legacy_module} is a compatibility shim; use {target_module} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def reexport(namespace: dict[str, Any], target_module: str) -> ModuleType:
    """Populate *namespace* from *target_module* and mark the redirect explicitly."""
    target = import_module(target_module)
    public_names = getattr(target, "__all__", None)
    if public_names is None:
        public_names = [name for name in vars(target) if not name.startswith("_")]

    for name in public_names:
        namespace[name] = getattr(target, name)

    namespace["__all__"] = list(public_names)
    namespace[COMPAT_TARGET_ATTR] = target_module

    def __getattr__(name: str) -> Any:
        return getattr(target, name)

    def __dir__() -> list[str]:
        return sorted(set(namespace["__all__"]) | set(dir(target)))

    namespace["__getattr__"] = __getattr__
    namespace["__dir__"] = __dir__

    _warn_once(
        legacy_module=str(namespace.get("__name__", target_module)),
        target_module=target_module,
    )
    return target
