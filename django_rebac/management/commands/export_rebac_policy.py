from django.core.management.base import BaseCommand
from django_rebac.models import TypeDefinition
import yaml
import os

class Command(BaseCommand):
    help = 'Export ReBAC policy from DB to YAML file'

    def add_arguments(self, parser):
        parser.add_argument('output', nargs='?', default='rebac_policy.yaml', help='Output YAML file path')

    def handle(self, *args, **options):
        output_path = options['output']
        policy = {}
        for type_def in TypeDefinition.objects.filter(is_active=True):
            policy[type_def.name] = type_def.as_dict()

        with open(output_path, 'w') as f:
            yaml.dump({'types': policy}, f, default_flow_style=False)

        self.stdout.write(self.style.SUCCESS(f'Policy exported to {output_path}'))
