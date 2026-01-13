from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "example_project.documents"

    def ready(self):
        from example_project.documents.signals import connect_group_membership_signals

        connect_group_membership_signals()
