"""Adapter factory and override hooks."""

from __future__ import annotations

from typing import Optional

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import RebacAdapter
from .spicedb import SpiceDBAdapter

_adapter: Optional[RebacAdapter] = None


def get_adapter() -> RebacAdapter:
    global _adapter
    if _adapter is not None:
        return _adapter

    config = getattr(settings, "REBAC", {}).get("adapter")
    if not isinstance(config, dict):
        raise ImproperlyConfigured("settings.REBAC['adapter'] must be configured to use SpiceDB.")

    endpoint = config.get("endpoint")
    token = config.get("token")
    if not endpoint or not token:
        raise ImproperlyConfigured("REBAC adapter configuration requires 'endpoint' and 'token'.")

    insecure = config.get("insecure", True)
    grpc_options = tuple(config.get("grpc_options", ()))

    _adapter = SpiceDBAdapter(
        endpoint=endpoint,
        token=token,
        insecure=insecure,
        grpc_options=grpc_options,
    )
    return _adapter


def set_adapter(adapter: RebacAdapter | None) -> None:
    global _adapter
    _adapter = adapter


def reset_adapter() -> None:
    global _adapter
    if _adapter:
        try:
            close = getattr(_adapter, "close", None)
            if callable(close):
                close()
        finally:
            _adapter = None
    else:
        _adapter = None
