"""Adapter interfaces for communicating with SpiceDB or compatible engines."""

from .base import RebacAdapter, TupleKey, TupleWrite
from .factory import get_adapter, reset_adapter, set_adapter
from .spicedb import SpiceDBAdapter

__all__ = [
    "RebacAdapter",
    "TupleKey",
    "TupleWrite",
    "SpiceDBAdapter",
    "get_adapter",
    "set_adapter",
    "reset_adapter",
]
