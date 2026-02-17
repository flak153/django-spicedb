"""Export ReBAC policy from DB to YAML file."""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Export ReBAC policy from DB to YAML file"

    def add_arguments(self, parser):
        parser.add_argument(
            "output",
            nargs="?",
            default="rebac_policy.yaml",
            help="Output YAML file path",
        )

    def handle(self, *args, **options):
        try:
            import yaml
        except ImportError:
            raise CommandError(
                "PyYAML is required for policy export. "
                "Install it with: pip install django-spicedb[yaml]"
            )

        from django_spicedb.models import TypeDefinition

        output_path = options["output"]
        policy = {}
        for type_def in TypeDefinition.objects.filter(is_active=True):
            policy[type_def.name] = type_def.as_dict()

        with open(output_path, "w") as f:
            yaml.dump({"types": policy}, f, default_flow_style=False)

        self.stdout.write(self.style.SUCCESS(f"Policy exported to {output_path}"))
