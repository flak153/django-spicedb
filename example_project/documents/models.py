from django.conf import settings
from django.db import models

from django_rebac.integrations.orm import RebacManager
from django_rebac.models import Resource


class Workspace(models.Model):
    name = models.CharField(max_length=128)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True)

    def __str__(self) -> str:
        return self.name


class Document(models.Model):
    title = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_documents",
    )
    resource = models.ForeignKey(
        "HierarchyResource",
        on_delete=models.CASCADE,
        related_name="documents",
        null=True,
        blank=True,
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="documents",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RebacManager()

    def __str__(self) -> str:
        return self.title


class HierarchyResource(Resource):
    """Sample hierarchy node demonstrating arbitrary parent/child trees."""

    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="managed_resources",
    )

    objects = RebacManager()

    class Meta:
        verbose_name = "Hierarchy resource"
        verbose_name_plural = "Hierarchy resources"

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        base = super().__str__()
        return base or f"HierarchyResource:{self.pk}"
