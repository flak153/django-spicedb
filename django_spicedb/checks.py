"""Django system checks for ReBAC configuration."""

import logging

from django.core.checks import Error, register, Tags

logger = logging.getLogger(__name__)


@register(Tags.models)
def check_rebac_configuration(app_configs, **kwargs):
    """Validate ReBAC model configurations."""
    errors = []

    try:
        from django_spicedb.core import get_rebac_model_registry
    except ImportError:
        return errors

    registry = get_rebac_model_registry()
    if not registry:
        return errors  # No ReBAC models registered yet

    for type_name, model_class in registry.items():
        rebac_meta = getattr(model_class, 'RebacMeta', None)
        if not rebac_meta:
            continue

        # Validate relation field references
        relations_map = getattr(rebac_meta, 'relations', {})
        for relation_name, relation_spec in relations_map.items():
            if isinstance(relation_spec, str):
                # It's a field name - verify it exists
                try:
                    model_class._meta.get_field(relation_spec)
                except Exception:
                    errors.append(
                        Error(
                            f"RebacMeta relation '{relation_name}' references "
                            f"field '{relation_spec}' which does not exist on {model_class.__name__}.",
                            obj=model_class,
                            id='django_spicedb.E001',
                        )
                    )
            elif isinstance(relation_spec, dict):
                field_name = relation_spec.get('field')
                if field_name:
                    try:
                        model_class._meta.get_field(field_name)
                    except Exception:
                        errors.append(
                            Error(
                                f"RebacMeta relation '{relation_name}' references "
                                f"field '{field_name}' which does not exist on {model_class.__name__}.",
                                obj=model_class,
                                id='django_spicedb.E001',
                            )
                        )

        # Validate through config
        through_config = getattr(rebac_meta, 'through', None)
        if through_config and isinstance(through_config, dict):
            for required_key in ('model', 'object_fk', 'subject_fk'):
                if not through_config.get(required_key):
                    errors.append(
                        Error(
                            f"RebacMeta.through on {model_class.__name__} is missing "
                            f"required key '{required_key}'.",
                            obj=model_class,
                            id='django_spicedb.E002',
                        )
                    )

    return errors
