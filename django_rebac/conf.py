"""Configuration helpers for django-spicedb."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .types import TypeGraph

_TYPE_GRAPH_CACHE: TypeGraph | None = None


def get_type_graph() -> TypeGraph:
    """Return the cached :class:`TypeGraph` built from Django settings."""

    global _TYPE_GRAPH_CACHE

    if _TYPE_GRAPH_CACHE is not None:
        return _TYPE_GRAPH_CACHE

    config = _get_rebac_settings()
    types_config = _collect_type_configs(config)

    if not types_config:
        raise ImproperlyConfigured("No type definitions available for TypeGraph.")

    graph = TypeGraph(types_config)
    _TYPE_GRAPH_CACHE = graph
    return graph


def reset_type_graph_cache() -> None:
    """Clear the cached ``TypeGraph``. Primarily intended for tests."""

    global _TYPE_GRAPH_CACHE
    _TYPE_GRAPH_CACHE = None


def _get_rebac_settings() -> MutableMapping[str, Any]:
    value = getattr(settings, "REBAC", None)
    if value is None:
        raise ImproperlyConfigured("settings.REBAC must be defined.")
    if not isinstance(value, MutableMapping):
        raise ImproperlyConfigured("settings.REBAC must be a mapping.")
    return value


def _collect_type_configs(config: Mapping[str, Any]) -> MutableMapping[str, Any]:
    base_types = config.get("types")
    if base_types is None:
        base_types = {}
    if not isinstance(base_types, Mapping):
        raise ImproperlyConfigured("settings.REBAC['types'] must be a mapping.")

    merged: MutableMapping[str, Any] = {}
    for name, value in base_types.items():
        if not isinstance(value, Mapping):
            raise ImproperlyConfigured(
                f"settings.REBAC['types'][{name!r}] must be a mapping."
            )
        merged[name] = dict(value)

    if config.get("db_overrides"):
        from django_rebac.models import TypeDefinition

        for type_def in TypeDefinition.objects.filter(is_active=True):
            merged[type_def.name] = type_def.as_dict()

    return merged
