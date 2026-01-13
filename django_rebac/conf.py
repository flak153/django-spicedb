"""Configuration helpers for django-rebac."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Type

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .types import TypeGraph

_TYPE_GRAPH_CACHE: TypeGraph | None = None
_MODEL_TYPE_CACHE: MutableMapping[str, str] = {}


def get_type_graph() -> TypeGraph:
    """
    Return the cached TypeGraph built from registered RebacModels.

    The TypeGraph is built by introspecting all Django models that have
    a RebacMeta inner class defined.
    """
    global _TYPE_GRAPH_CACHE

    if _TYPE_GRAPH_CACHE is not None:
        return _TYPE_GRAPH_CACHE

    from .core import build_type_configs_from_registry

    types_config = build_type_configs_from_registry()

    if not types_config:
        raise ImproperlyConfigured(
            "No ReBAC models found. Ensure your models inherit from RebacModel "
            "and have a RebacMeta inner class defined."
        )

    graph = TypeGraph(types_config)
    _rebuild_model_cache(graph)
    _TYPE_GRAPH_CACHE = graph
    return graph


def reset_type_graph_cache() -> None:
    """Clear the cached TypeGraph. Primarily intended for tests."""
    global _TYPE_GRAPH_CACHE, _MODEL_TYPE_CACHE
    _TYPE_GRAPH_CACHE = None
    _MODEL_TYPE_CACHE = {}


def get_rebac_settings() -> MutableMapping[str, Any]:
    """
    Return the REBAC settings dict.

    Only adapter configuration is required:

        REBAC = {
            "adapter": {
                "endpoint": "localhost:50051",
                "token": "your-token",
                "insecure": True,
            },
        }
    """
    value = getattr(settings, "REBAC", None)
    if value is None:
        return {}
    if not isinstance(value, MutableMapping):
        raise ImproperlyConfigured("settings.REBAC must be a mapping.")
    return value


def get_adapter_settings() -> Mapping[str, Any]:
    """Return the adapter configuration from settings."""
    config = get_rebac_settings()
    return config.get("adapter", {})


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
        "Ensure the model inherits from RebacModel and has RebacMeta defined."
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
    config = get_rebac_settings()
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
    config = get_rebac_settings()
    return config.get("tenant_fk_name", "tenant")
