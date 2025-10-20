"""Core package for django-spicedb.

The initial scaffolding keeps the public surface minimal while we grow the
planned abstractions.  Modules that need to be public should import their
symbols here once they stabilise.
"""

from .types.graph import TypeGraph

__all__ = ["TypeGraph"]
