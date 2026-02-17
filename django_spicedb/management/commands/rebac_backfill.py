"""Management command to backfill SpiceDB tuples from existing Django data."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill SpiceDB tuples from existing Django data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of tuples to write per batch (default: 100)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count tuples without writing to SpiceDB",
        )
        parser.add_argument(
            "--types",
            nargs="*",
            help="Only backfill specific types (space-separated)",
        )

    def handle(self, *args, **options):
        from django.utils.module_loading import import_string

        from django_spicedb.adapters.factory import get_adapter
        from django_spicedb.conf import get_type_graph
        from django_spicedb.sync.backfill import backfill_tuples, generate_through_tuples
        from django_spicedb.sync.registry import _gather_tuple_writes

        graph = get_type_graph()
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        filter_types = options.get("types")

        type_names = filter_types if filter_types else list(graph.types.keys())

        adapter = None if dry_run else get_adapter()

        grand_total = 0

        for type_name in type_names:
            cfg = graph.types.get(type_name)
            if cfg is None:
                self.stdout.write(self.style.WARNING(f"Type {type_name!r} not found, skipping"))
                continue

            if not cfg.model:
                continue

            if not cfg.bindings:
                continue

            model = import_string(cfg.model)
            tuples = []

            # Gather FK/M2M tuples from all instances
            for instance in model.objects.iterator():
                tuples.extend(_gather_tuple_writes(type_name, cfg, instance))

            # Gather through-table tuples
            cfg_dict = {
                "bindings": cfg.bindings,
                "relations": cfg.relations,
            }
            tuples.extend(generate_through_tuples(type_name, cfg_dict))

            count = len(tuples)
            grand_total += count

            if dry_run:
                self.stdout.write(f"  {type_name}: {count} tuples")
            else:
                written = backfill_tuples(adapter, tuples, batch_size=batch_size)
                self.stdout.write(f"  {type_name}: {written} tuples written")

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nDry run: {grand_total} tuples would be written"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nBackfill complete: {grand_total} tuples written"))
