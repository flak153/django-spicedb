from django.apps import AppConfig


class DjangoRebacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_rebac"
    verbose_name = "Django ReBAC"

    def ready(self) -> None:  # pragma: no cover - import side effects
        from . import signals  # noqa: F401
        from .sync import registry

        try:
            registry.refresh()
        except Exception:  # pragma: no cover - defensive startup guard
            pass
