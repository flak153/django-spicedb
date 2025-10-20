"""Adapter interfaces for communicating with SpiceDB or compatible engines."""

from .base import RebacAdapter, TupleKey, TupleWrite
from .fake import FakeAdapter

__all__ = [
    "RebacAdapter",
    "TupleKey",
    "TupleWrite",
    "FakeAdapter",
]
