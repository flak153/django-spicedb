import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class DjangoSpicedbConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_spicedb"
    verbose_name = "Django ReBAC"

    def ready(self) -> None:
        # Import signals to connect handlers
        from . import signals  # noqa: F401
        from . import checks  # noqa: F401

        # Import sync registry and refresh signal handlers
        from .sync import registry

        # Reset and rebuild the type graph from model registry
        from .conf import reset_type_graph_cache

        reset_type_graph_cache()

        registry.refresh()
