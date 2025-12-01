"""Configuration helpers for django-spicedb."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Type

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .types import TypeGraph

_TYPE_GRAPH_CACHE: TypeGraph | None = None
_MODEL_TYPE_CACHE: MutableMapping[str, str] = {}


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
    _rebuild_model_cache(graph)
    _TYPE_GRAPH_CACHE = graph
    return graph


def reset_type_graph_cache() -> None:
    """Clear the cached ``TypeGraph``. Primarily intended for tests."""

    global _TYPE_GRAPH_CACHE, _MODEL_TYPE_CACHE
    _TYPE_GRAPH_CACHE = None
    _MODEL_TYPE_CACHE = {}


def _get_rebac_settings() -> MutableMapping[str, Any]:
    value = getattr(settings, "REBAC", None)
    if value is None:
        raise ImproperlyConfigured("settings.REBAC must be defined.")
    if not isinstance(value, MutableMapping):
        raise ImproperlyConfigured("settings.REBAC must be a mapping.")
    return value


import yaml
import os

def _collect_type_configs(config: Mapping[str, Any]) -> MutableMapping[str, Any]:
    merged: MutableMapping[str, Any] = {}

    # Priority 1: Load from YAML file if exists
    yaml_path = config.get('POLICY_FILE', 'rebac_policy.yaml')
    if os.path.exists(yaml_path):
        with open(yaml_path, 'r') as f:
            yaml_data = yaml.safe_load(f)
            yaml_types = yaml_data.get('types', {})
            for name, value in yaml_types.items():
                if isinstance(value, Mapping):
                    merged[name] = dict(value)
        return merged  # YAML takes full precedence; early return

    # Priority 2: DB overrides if enabled
    if config.get("db_overrides"):
        from django_rebac.models import TypeDefinition

        for type_def in TypeDefinition.objects.filter(is_active=True):
            merged[type_def.name] = type_def.as_dict()

    # Priority 3: Fallback to settings
    base_types = config.get("types", {})
    if not isinstance(base_types, Mapping):
        raise ImproperlyConfigured("settings.REBAC['types'] must be a mapping.")

    for name, value in base_types.items():
        if isinstance(value, Mapping):
            if name not in merged:  # Only add if not overridden
                merged[name] = dict(value)

    if not merged:
        raise ImproperlyConfigured("No type definitions available from YAML, DB, or settings.")

    return merged


def get_type_for_model(model: Type[Any] | str) -> str:
    """
    Return the configured SpiceDB type name for the given Django model.

    Raises ImproperlyConfigured if the model is not associated with any type.
    """

    if isinstance(model, str):
        model_path = model
    else:
        model_path = f"{model.__module__}.{model.__name__}"

    if model_path in _MODEL_TYPE_CACHE:
        return _MODEL_TYPE_CACHE[model_path]

    graph = get_type_graph()
    for type_name, cfg in graph.types.items():
        if cfg.model == model_path:
            _MODEL_TYPE_CACHE[model_path] = type_name
            return type_name

    raise ImproperlyConfigured(
        f"No REBAC type configured for model {model_path!r}. "
        "Ensure settings.REBAC includes a type with this model."
    )


def _rebuild_model_cache(graph: TypeGraph) -> None:
    global _MODEL_TYPE_CACHE
    _MODEL_TYPE_CACHE = {}
    for type_name, cfg in graph.types.items():
        if cfg.model:
            _MODEL_TYPE_CACHE[cfg.model] = type_name


# =============================================================================
# Tenant Configuration Helpers
# =============================================================================


def get_tenant_model() -> Type[Any]:
    """
    Return the Django model class configured as the tenant model.

    Configure via ``REBAC['tenant_model'] = 'myapp.Company'``.

    Raises:
        ValueError: If ``tenant_model`` is not configured in settings.
        ImproperlyConfigured: If the model cannot be imported.
    """
    config = _get_rebac_settings()
    tenant_model_path = config.get("tenant_model")

    if not tenant_model_path:
        raise ValueError(
            "REBAC['tenant_model'] is not configured. "
            "Set it to your tenant model path, e.g., 'myapp.Company'."
        )

    try:
        return import_string(tenant_model_path)
    except ImportError as e:
        raise ImproperlyConfigured(
            f"Could not import tenant model {tenant_model_path!r}: {e}"
        ) from e


def get_tenant_content_type():
    """
    Return the ContentType for the configured tenant model.

    Returns:
        ContentType: The ContentType instance for the tenant model.
    """
    from django.contrib.contenttypes.models import ContentType

    tenant_model = get_tenant_model()
    return ContentType.objects.get_for_model(tenant_model)


def get_tenant_fk_name() -> str:
    """
    Return the FK field name for tenant relationships.

    Configure via ``REBAC['tenant_fk_name'] = 'company'``.
    Defaults to ``'tenant'`` if not configured.
    """
    config = _get_rebac_settings()
    return config.get("tenant_fk_name", "tenant")
