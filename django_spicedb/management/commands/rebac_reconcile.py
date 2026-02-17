"""Management command to reconcile ReBAC tuples between Django and SpiceDB."""

from django.core.management.base import BaseCommand

from django_spicedb.sync.reconcile import reconcile_tuples


class Command(BaseCommand):
    help = "Reconcile ReBAC tuples between Django and SpiceDB"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Apply fixes by writing tuples to SpiceDB",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done without making changes",
        )
        parser.add_argument(
            "--type",
            action="append",
            dest="types",
            help="Reconcile specific type(s) only (can be repeated)",
        )

    def handle(self, *args, **options):
        fix = options["fix"]
        dry_run = options["dry_run"]
        types = options["types"]

        # Validate flags
        if fix and dry_run:
            self.stdout.write(
                self.style.ERROR("Cannot use --fix and --dry-run together")
            )
            return

        # Set mode message
        if fix:
            mode = self.style.WARNING("FIX MODE")
            self.stdout.write(f"\n{mode}: Tuples will be written to SpiceDB")
        elif dry_run:
            mode = self.style.NOTICE("DRY RUN MODE")
            self.stdout.write(f"\n{mode}: No changes will be made")
        else:
            mode = self.style.NOTICE("REPORT MODE")
            self.stdout.write(f"\n{mode}: Reporting expected tuple counts")

        # Run reconciliation
        self.stdout.write("\nReconciling tuples...\n")

        results = reconcile_tuples(fix=fix, types=types, dry_run=dry_run)

        # Print summary table
        if not results:
            self.stdout.write(self.style.WARNING("No types to reconcile"))
            return

        # Calculate column widths
        max_type_len = max(len(r.type_name) for r in results)
        type_width = max(max_type_len, len("TYPE"))

        # Print header
        self.stdout.write("\n" + "=" * (type_width + 50))
        header = (
            f"{'TYPE':<{type_width}}  {'EXPECTED':>10}  "
            f"{'TO WRITE':>10}  {'STALE':>10}  {'FIXED':>8}"
        )
        self.stdout.write(self.style.SUCCESS(header))
        self.stdout.write("=" * (type_width + 50))

        # Print rows
        for result in results:
            if result.expected > 0:
                type_style = self.style.SUCCESS
            else:
                type_style = self.style.WARNING
            if result.to_write > 0:
                to_write_style = self.style.WARNING
            else:
                to_write_style = self.style.SUCCESS
            if result.stale > 0:
                stale_style = self.style.ERROR
            else:
                stale_style = self.style.SUCCESS
            if result.fixed:
                fixed_style = self.style.SUCCESS
            else:
                fixed_style = self.style.NOTICE

            # Format values first, then apply styles
            type_name_formatted = f"{result.type_name:<{type_width}}"
            to_write_formatted = f"{result.to_write:>10}"
            stale_formatted = f"{result.stale:>10}"
            fixed_formatted = f"{result.fixed!s:>8}"

            row = (
                f"{type_style(type_name_formatted)}  "
                f"{result.expected:>10}  "
                f"{to_write_style(to_write_formatted)}  "
                f"{stale_style(stale_formatted)}  "
                f"{fixed_style(fixed_formatted)}"
            )
            self.stdout.write(row)

        # Print totals
        total_expected = sum(r.expected for r in results)
        total_to_write = sum(r.to_write for r in results)
        total_stale = sum(r.stale for r in results)
        any_fixed = any(r.fixed for r in results)

        self.stdout.write("=" * (type_width + 50))
        totals = (
            f"{'TOTAL':<{type_width}}  "
            f"{total_expected:>10}  "
            f"{total_to_write:>10}  "
            f"{total_stale:>10}  "
            f"{any_fixed!s:>8}"
        )
        self.stdout.write(self.style.SUCCESS(totals))
        self.stdout.write("=" * (type_width + 50))

        # Print summary message
        self.stdout.write("")
        if fix and any_fixed:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully wrote {total_to_write} tuples to SpiceDB"
                )
            )
        elif total_to_write > 0:
            msg = (
                f"Found {total_to_write} tuples to write. "
                "Run with --fix to write them."
            )
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(
                self.style.SUCCESS("All types are in sync!")
            )

        # Note about stale detection
        if total_stale == 0:
            note = (
                "\nNote: Stale tuple detection requires a read_tuples() "
                "adapter method (not yet implemented)."
            )
            self.stdout.write(self.style.NOTICE(note))

        self.stdout.write("")
