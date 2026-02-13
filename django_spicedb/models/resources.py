"""Resource base classes for hierarchical models."""

from __future__ import annotations

from django.db import models

from .base import RebacModel


class Resource(RebacModel):
    """Abstract base model for hierarchical resources."""

    name = models.CharField(max_length=255, blank=True)
    slug = models.SlugField(max_length=255, blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:  # pragma: no cover
        if self.name:
            return self.name
        if self.slug:
            return self.slug
        return f"{self.__class__.__name__}:{self.pk}"


class ResourceNode(Resource):
    """Concrete resource node for apps that want a ready-made hierarchy."""

    class Meta:
        verbose_name = "Resource node"
        verbose_name_plural = "Resource nodes"
