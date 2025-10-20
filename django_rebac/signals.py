from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import django_rebac.conf as conf
from django_rebac.models import TypeDefinition


@receiver([post_save, post_delete], sender=TypeDefinition)
def clear_type_graph_cache(**_: object) -> None:
    conf.reset_type_graph_cache()
