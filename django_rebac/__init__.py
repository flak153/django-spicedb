"""Core package for django-rebac."""

from .types.graph import TypeGraph


def __getattr__(name: str):
    """Lazy import for RebacModel and register_type to avoid circular imports."""
    if name == "RebacModel":
        from .models import RebacModel
        return RebacModel
    if name == "register_type":
        from .core import register_type
        return register_type
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["RebacModel", "register_type", "TypeGraph"]
