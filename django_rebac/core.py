"""Model-centric ReBAC configuration registry and utilities."""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Mapping,
    MutableMapping,
    Optional,
    TYPE_CHECKING,
    Type,
)

if TYPE_CHECKING:
    from django.db import models as django_models


# Global registry of models with RebacMeta
_REBAC_MODEL_REGISTRY: Dict[str, Type["django_models.Model"]] = {}


def get_rebac_model_registry() -> Mapping[str, Type["django_models.Model"]]:
    """Return a read-only view of registered ReBAC models."""
    return dict(_REBAC_MODEL_REGISTRY)


def clear_rebac_model_registry() -> None:
    """Clear the registry. Primarily for tests."""
    _REBAC_MODEL_REGISTRY.clear()


def _get_type_name(model_class: Type["django_models.Model"]) -> str:
    """
    Derive the SpiceDB type name for a model.

    Uses RebacMeta.type_name if set, otherwise converts class name to snake_case.
    """
    rebac_meta = getattr(model_class, 'RebacMeta', None)
    if rebac_meta and hasattr(rebac_meta, 'type_name'):
        return rebac_meta.type_name

    # Convert CamelCase to snake_case
    name = model_class.__name__
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append('_')
        result.append(char.lower())
    return ''.join(result)


def _get_model_path(model_class: Type["django_models.Model"]) -> str:
    """Return the full dotted path for a model class."""
    return f"{model_class.__module__}.{model_class.__name__}"


def _infer_binding_kind(field: Any) -> Optional[str]:
    """Infer the binding kind from a Django field type."""
    from django.db import models

    if isinstance(field, models.ForeignKey):
        return 'fk'
    if isinstance(field, models.ManyToManyField):
        return 'm2m'
    return None


def register_rebac_model(model_class: Type["django_models.Model"]) -> None:
    """Register a model with RebacMeta to the global registry."""
    type_name = _get_type_name(model_class)
    _REBAC_MODEL_REGISTRY[type_name] = model_class


def register_type(
    model_class: Type["django_models.Model"],
    type_name: Optional[str] = None,
    relations: Optional[Mapping[str, str]] = None,
    permissions: Optional[Mapping[str, str]] = None,
) -> Type["django_models.Model"]:
    """
    Register a third-party model as a ReBAC type.

    Use this for models you don't control (like django.contrib.auth.User).

    Can be used as a decorator:

        @register_type(type_name="user")
        class CustomUser(AbstractUser):
            pass

    Or called directly:

        from django.contrib.auth.models import User
        register_type(User, type_name="user")

    Args:
        model_class: The Django model class to register
        type_name: SpiceDB type name (defaults to snake_case of class name)
        relations: Optional dict of relation_name → field_name
        permissions: Optional dict of permission_name → expression

    Returns:
        The model class (for decorator usage)
    """
    # Create a synthetic RebacMeta if needed
    if not hasattr(model_class, 'RebacMeta'):
        class RebacMeta:
            pass
        model_class.RebacMeta = RebacMeta

    if type_name:
        model_class.RebacMeta.type_name = type_name
    if relations:
        model_class.RebacMeta.relations = relations
    if permissions:
        model_class.RebacMeta.permissions = permissions

    # Use provided type_name or derive it
    final_type_name = type_name or _get_type_name(model_class)
    _REBAC_MODEL_REGISTRY[final_type_name] = model_class

    return model_class


def build_type_configs_from_registry() -> MutableMapping[str, Any]:
    """
    Build TypeGraph-compatible configs from all registered RebacModels.

    This introspects each registered model's fields and RebacMeta to produce
    the configuration dict that TypeGraph expects.

    RebacMeta.relations can specify relations in two ways:

    1. Field-based (auto-binding): relation_name → field_name
       The subject type is inferred from the field's related model.
       ```
       relations = {
           "owner": "owner",      # FK field, subject inferred
           "members": "members",  # M2M field, subject inferred
       }
       ```

    2. Manual (no binding): relation_name → {"subject": "type_name"}
       The subject type is specified directly, no auto-binding.
       ```
       relations = {
           "viewer": {"subject": "user"},  # Manual, no field binding
       }
       ```
    """
    configs: MutableMapping[str, Any] = {}

    # First pass: collect all models and their type names
    for type_name, model_class in _REBAC_MODEL_REGISTRY.items():
        rebac_meta = getattr(model_class, 'RebacMeta', None)
        model_path = _get_model_path(model_class)

        config: MutableMapping[str, Any] = {
            'model': model_path,
            'relations': {},
            'permissions': {},
            'bindings': {},
        }

        if rebac_meta:
            # Get relations from RebacMeta
            relations_map = getattr(rebac_meta, 'relations', {})
            for relation_name, relation_spec in relations_map.items():
                # Check if it's a manual relation (dict with 'subject')
                if isinstance(relation_spec, dict):
                    subject_type = relation_spec.get('subject')
                    if subject_type:
                        config['relations'][relation_name] = subject_type
                    # Check if field is also specified for binding
                    field_name = relation_spec.get('field')
                    if field_name:
                        try:
                            field = model_class._meta.get_field(field_name)
                            binding_kind = _infer_binding_kind(field)
                            if binding_kind:
                                config['bindings'][relation_name] = {
                                    'field': field_name,
                                    'kind': binding_kind,
                                }
                        except Exception:
                            pass
                    continue

                # It's a field name (string) - infer subject from field
                field_name = relation_spec
                try:
                    field = model_class._meta.get_field(field_name)
                except Exception:
                    continue

                # Determine subject type from related model
                related_model = getattr(field, 'related_model', None)
                if related_model is not None:
                    # Handle self-referential
                    if related_model == model_class:
                        subject_type = type_name
                    else:
                        # Look up related model's type name
                        subject_type = None
                        related_path = _get_model_path(related_model)
                        for t_name, t_model in _REBAC_MODEL_REGISTRY.items():
                            if _get_model_path(t_model) == related_path:
                                subject_type = t_name
                                break

                        if subject_type is None:
                            # Related model not registered, skip
                            continue

                    config['relations'][relation_name] = subject_type

                    # Auto-infer binding
                    binding_kind = _infer_binding_kind(field)
                    if binding_kind:
                        config['bindings'][relation_name] = {
                            'field': field_name,
                            'kind': binding_kind,
                        }

            # Get permissions from RebacMeta
            permissions = getattr(rebac_meta, 'permissions', {})
            config['permissions'] = dict(permissions)

            # Get parents if defined
            parents = getattr(rebac_meta, 'parents', None)
            if parents:
                config['parents'] = list(parents)

        configs[type_name] = config

    return configs
