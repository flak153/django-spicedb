from django.apps import AppConfig


class DjangoRebacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_rebac"
    verbose_name = "Django ReBAC"

    def ready(self) -> None:
        # Import signals to connect handlers
        from . import signals  # noqa: F401

        # Import sync registry and refresh signal handlers
        from .sync import registry

        # Reset and rebuild the type graph from model registry
        from .conf import reset_type_graph_cache

        reset_type_graph_cache()

        try:
            registry.refresh()
        except Exception:
            # Defensive guard during startup - models might not be ready yet
            pass
