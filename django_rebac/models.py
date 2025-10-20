"""Database models backing django-spicedb."""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class TypeDefinition(models.Model):
    """Stores a single type declaration editable via admin."""

    name = models.CharField(max_length=128, unique=True)
    relations = models.JSONField(default=dict, blank=True)
    permissions = models.JSONField(default=dict, blank=True)
    parents = models.JSONField(default=list, blank=True)
    bindings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def as_dict(self) -> dict[str, object]:
        """Return the dict shape consumed by :class:`TypeGraph`."""

        return {
            "relations": self.relations or {},
            "permissions": self.permissions or {},
            "parents": self.parents or [],
            "bindings": self.bindings or {},
        }

    def __str__(self) -> str:  # pragma: no cover - admin nicety
        return self.name


class Grant(models.Model):
    """Represents a relation or role granted to a subject on an object."""

    subject_type = models.CharField(max_length=64)
    subject_id = models.CharField(max_length=128)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=128)
    relation = models.CharField(max_length=64, blank=True)
    role = models.CharField(max_length=64, blank=True)
    caveat_name = models.CharField(max_length=128, blank=True)
    caveat_params = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "subject_type",
                    "subject_id",
                    "object_type",
                    "object_id",
                    "relation",
                    "role",
                ),
                name="rebac_unique_grant",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"{self.subject_type}:{self.subject_id} -> "
            f"{self.object_type}:{self.object_id} ({self.relation or self.role})"
        )


class Job(models.Model):
    """Captures long-running publish/backfill operations."""

    KIND_PUBLISH = "publish"
    KIND_BACKFILL = "backfill"
    KIND_CHOICES = [
        (KIND_PUBLISH, "Publish"),
        (KIND_BACKFILL, "Backfill"),
    ]

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def mark_running(self) -> None:
        self.status = self.STATUS_RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=("status", "started_at", "updated_at"))

    def mark_complete(self, success: bool) -> None:
        self.status = self.STATUS_SUCCEEDED if success else self.STATUS_FAILED
        self.finished_at = timezone.now()
        self.save(update_fields=("status", "finished_at", "updated_at"))


class AuditLog(models.Model):
    """Simple audit trail for policy/grant changes."""

    action = models.CharField(max_length=64)
    actor = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.action} @ {self.created_at.isoformat()}"
