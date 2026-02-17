"""Management command to compile and publish the ReBAC schema to SpiceDB."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compile and publish the ReBAC schema to SpiceDB"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the compiled schema without publishing to SpiceDB",
        )

    def handle(self, *args, **options):
        from django_spicedb.conf import get_type_graph
        from django_spicedb.schema import compile_schema, publish_schema
        from django_spicedb.adapters.factory import get_adapter

        graph = get_type_graph()
        schema, digest = compile_schema(graph)

        if options["dry_run"]:
            self.stdout.write(schema)
            self.stdout.write(self.style.SUCCESS(f"\nDigest: {digest[:12]}"))
            return

        adapter = get_adapter()
        publish_schema(adapter, graph=graph)
        self.stdout.write(self.style.SUCCESS(f"Schema published (digest: {digest[:12]})"))
