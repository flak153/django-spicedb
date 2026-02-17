"""Publish compiled ReBAC schema to SpiceDB."""

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from django_spicedb.conf import get_type_graph
from django_spicedb.schema import publish_schema


class Command(BaseCommand):
    help = "Compile and publish the current ReBAC schema to SpiceDB"

    def handle(self, *args, **options):
        graph = get_type_graph()

        try:
            from django_spicedb.adapters import factory
            adapter = factory.get_adapter()
        except ImproperlyConfigured as exc:
            raise CommandError(
                f"SpiceDB adapter is not configured: {exc}\n"
                "Set REBAC['adapter'] in settings with 'endpoint' and 'token'."
            ) from exc

        try:
            digest = publish_schema(adapter, graph=graph)
        except Exception as exc:
            raise CommandError(
                f"Failed to publish schema to SpiceDB: {exc}\n"
                "Check that SpiceDB is running and the endpoint/token are correct."
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Published schema for {len(graph.types)} type(s). Digest: {digest}"
            )
        )
