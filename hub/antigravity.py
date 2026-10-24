"""Compatibility alias only; implementation is owned by the harness module."""
import sys as _sys
from importlib import import_module as _import_module
_sys.modules[__name__] = _import_module("hub.builtin_adapters.antigravity.runtime")
