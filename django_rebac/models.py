"""Database models backing django-rebac."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from django.db import models
from django.utils import timezone

from django_rebac.integrations.orm import TenantAwareRebacManager

if TYPE_CHECKING:
    from django.db.models import Model as DjangoModel


# =============================================================================
# RebacModel Base Class
# =============================================================================


class RebacModelBase(models.base.ModelBase):
    """
    Metaclass that registers Django models with RebacMeta.

    When a model class with a RebacMeta inner class is defined,
    this metaclass automatically registers it to the global registry.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple,
        namespace: dict,
        **kwargs: Any,
    ) -> "RebacModelBase":
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        # Don't register abstract models or the base RebacModel itself
        if hasattr(cls, '_meta') and not cls._meta.abstract:
            if hasattr(cls, 'RebacMeta'):
                from django_rebac.core import register_rebac_model
                register_rebac_model(cls)

        return cls


class RebacModel(models.Model, metaclass=RebacModelBase):
    """
    Base class for Django models with ReBAC permissions.

    Models inheriting from RebacModel can define a RebacMeta inner class
    to configure relations and permissions:

        class Document(RebacModel):
            owner = models.ForeignKey(User, on_delete=models.CASCADE)
            folder = models.ForeignKey(Folder, on_delete=models.CASCADE)

            class RebacMeta:
                type_name = "document"  # optional, defaults to snake_case
                relations = {
                    "owner": "owner",    # relation_name: field_name
                    "parent": "folder",  # can rename
                }
                permissions = {
                    "view": "owner + parent->view",
                    "edit": "owner",
                }
    """

    class Meta:
        abstract = True

    def grant(self, subject: "DjangoModel | str", relation: str) -> None:
        """
        Grant a relation to a subject on this object.

        Args:
            subject: A Django model instance or "type:id" string
            relation: The relation name to grant
        """
        from .adapters import get_adapter
        from .adapters.base import TupleKey, TupleWrite
        from .conf import get_type_for_model

        adapter = get_adapter()

        # Build object reference
        object_type = get_type_for_model(self.__class__)
        object_ref = f"{object_type}:{self.pk}"

        # Build subject reference
        if isinstance(subject, models.Model):
            subject_type = get_type_for_model(subject.__class__)
            subject_ref = f"{subject_type}:{subject.pk}"
        else:
            subject_ref = subject

        tuple_write = TupleWrite(
            key=TupleKey(
                object=object_ref,
                relation=relation,
                subject=subject_ref,
            )
        )
        adapter.write_tuples([tuple_write])

    def revoke(self, subject: "DjangoModel | str", relation: str) -> None:
        """
        Revoke a relation from a subject on this object.

        Args:
            subject: A Django model instance or "type:id" string
            relation: The relation name to revoke
        """
        from .adapters import get_adapter
        from .adapters.base import TupleKey
        from .conf import get_type_for_model

        adapter = get_adapter()

        # Build object reference
        object_type = get_type_for_model(self.__class__)
        object_ref = f"{object_type}:{self.pk}"

        # Build subject reference
        if isinstance(subject, models.Model):
            subject_type = get_type_for_model(subject.__class__)
            subject_ref = f"{subject_type}:{subject.pk}"
        else:
            subject_ref = subject

        tuple_key = TupleKey(
            object=object_ref,
            relation=relation,
            subject=subject_ref,
        )
        adapter.delete_tuples([tuple_key])

    def has_perm(self, subject: "DjangoModel | str", permission: str) -> bool:
        """
        Check if a subject has a permission on this object.

        Args:
            subject: A Django model instance or "type:id" string
            permission: The permission to check

        Returns:
            True if the subject has the permission
        """
        from .runtime import can
        return can(subject, permission, self)


# =============================================================================
# TypeDefinition and Grant Models (for runtime configuration)
# =============================================================================


class TypeDefinition(models.Model):
    """Stores a single type declaration editable via admin."""

    name = models.CharField(max_length=128, unique=True)
    model = models.CharField(max_length=255, blank=True)
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
        data = {
            "relations": self.relations or {},
            "permissions": self.permissions or {},
            "parents": self.parents or [],
            "bindings": self.bindings or {},
        }
        if self.model:
            data["model"] = self.model
        return data

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


# =============================================================================
# Resource Base Classes
# =============================================================================


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


# =============================================================================
# Multi-Tenant Hierarchy Models
# =============================================================================


class HierarchyTypeDefinition(models.Model):
    """
    Defines a hierarchy level TYPE for a specific tenant.

    Each tenant can define their own hierarchy structure (e.g., Region → Branch → Department).
    This model stores the type definitions, not the actual instances.

    The tenant FK uses a swappable model configured via REBAC['tenant_model'].
    """

    # Note: tenant FK is added dynamically in apps.py based on REBAC['tenant_model']
    # For now, we store tenant_id as a CharField to avoid circular imports
    tenant_content_type = models.ForeignKey(
        "contenttypes.ContentType",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="Content type of the tenant model",
    )
    tenant_object_id = models.CharField(
        max_length=128,
        help_text="Primary key of the tenant",
    )

    name = models.CharField(
        max_length=128,
        help_text="Internal name (e.g., 'region', 'branch')",
    )
    display_name = models.CharField(
        max_length=255,
        help_text="Human-readable name (e.g., 'Region', 'Branch')",
    )
    slug = models.SlugField(
        max_length=128,
        help_text="URL-safe identifier",
    )

    level = models.PositiveIntegerField(
        default=0,
        help_text="Position in hierarchy (0 = root level)",
    )
    parent_type = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_types",
        help_text="What type can be a parent (null = root type)",
    )

    # Relations and permissions for this type
    relations = models.JSONField(
        default=dict,
        blank=True,
        help_text='Relation definitions, e.g., {"manager": "user", "viewer": "user"}',
    )
    permissions = models.JSONField(
        default=dict,
        blank=True,
        help_text='Permission definitions, e.g., {"manage": "manager + parent->manage"}',
    )

    # UI metadata
    icon = models.CharField(
        max_length=64,
        blank=True,
        help_text="Icon identifier for UI",
    )
    color = models.CharField(
        max_length=32,
        blank=True,
        help_text="Color code for UI",
    )
    metadata_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON schema for node metadata validation",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hierarchy type definition"
        verbose_name_plural = "Hierarchy type definitions"
        ordering = ("tenant_content_type", "tenant_object_id", "level", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_content_type", "tenant_object_id", "slug"),
                name="rebac_unique_hierarchy_type_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_content_type", "tenant_object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.display_name} (level {self.level})"

    @property
    def spicedb_type_name(self) -> str:
        """Returns the SpiceDB type name for this hierarchy type."""
        return "hierarchy_node"


class HierarchyNode(RebacModel):
    """
    Actual hierarchy node instances for a tenant.

    These are the concrete nodes in the org structure (e.g., "North Region",
    "Downtown Branch", "Engineering Department").
    """

    # Tenant reference (same pattern as HierarchyTypeDefinition)
    tenant_content_type = models.ForeignKey(
        "contenttypes.ContentType",
        on_delete=models.CASCADE,
        related_name="+",
    )
    tenant_object_id = models.CharField(max_length=128)

    hierarchy_type = models.ForeignKey(
        HierarchyTypeDefinition,
        on_delete=models.PROTECT,
        related_name="nodes",
        help_text="The type of this node (Region, Branch, etc.)",
    )

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True)
    code = models.CharField(
        max_length=64,
        blank=True,
        help_text="Optional external code/identifier",
    )

    # Self-referential for tree structure
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    # Denormalized path for efficient ancestor/descendant queries
    path = models.CharField(
        max_length=1024,
        blank=True,
        db_index=True,
        help_text="Materialized path (e.g., '/1/5/12/')",
    )
    depth = models.PositiveIntegerField(
        default=0,
        help_text="Depth in the hierarchy (0 = root)",
    )

    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantAwareRebacManager()

    class Meta:
        verbose_name = "Hierarchy node"
        verbose_name_plural = "Hierarchy nodes"
        ordering = ("tenant_content_type", "tenant_object_id", "path", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_content_type", "tenant_object_id", "slug"),
                name="rebac_unique_hierarchy_node_slug",
                condition=models.Q(slug__gt=""),
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_content_type", "tenant_object_id"]),
            models.Index(fields=["tenant_content_type", "tenant_object_id", "path"]),
            models.Index(fields=["tenant_content_type", "tenant_object_id", "hierarchy_type"]),
        ]

    class RebacMeta:
        type_name = "hierarchy_node"
        relations = {
            "parent": "parent",  # FK field, auto-inferred
            # Role relations - assigned through HierarchyNodeRole, manual binding
            "owner": {"subject": "user"},
            "manager": {"subject": "user"},
            "lead": {"subject": "user"},
            "member": {"subject": "user"},
            "viewer": {"subject": "user"},
            "admin": {"subject": "user"},
        }
        permissions = {
            "view": "owner + manager + lead + member + viewer + admin + parent->view",
            "manage": "owner + manager + lead + admin + parent->manage",
        }

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        # Auto-compute path and depth
        if self.parent:
            self.depth = self.parent.depth + 1
        else:
            self.depth = 0

        # Save first to get pk
        super().save(*args, **kwargs)

        # Update path after save (need pk)
        if self.parent:
            new_path = f"{self.parent.path}{self.pk}/"
        else:
            new_path = f"/{self.pk}/"

        if self.path != new_path:
            self.path = new_path
            # Update only path field to avoid recursion
            HierarchyNode.objects.filter(pk=self.pk).update(path=new_path)

    @property
    def spicedb_object_ref(self) -> str:
        """Returns the SpiceDB object reference for this node."""
        return f"hierarchy_node:{self.pk}"

    def get_ancestors(self, include_self: bool = False):
        """Return all ancestors of this node."""
        if not self.path:
            return HierarchyNode.objects.none()

        # Extract ancestor IDs from path
        parts = [p for p in self.path.split("/") if p]
        if not include_self and parts:
            parts = parts[:-1]

        if not parts:
            return HierarchyNode.objects.none()

        return HierarchyNode.objects.filter(pk__in=parts).order_by("depth")

    def get_descendants(self, include_self: bool = False):
        """Return all descendants of this node."""
        if include_self:
            return HierarchyNode.objects.filter(path__startswith=self.path)
        return HierarchyNode.objects.filter(
            path__startswith=self.path
        ).exclude(pk=self.pk)


class HierarchyNodeRole(models.Model):
    """
    Through table for user-to-node role assignments.

    This represents "User X has role Y on Node Z" (e.g., "Alice is a manager of North Region").
    """

    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_VIEWER = "viewer"
    ROLE_ADMIN = "admin"
    ROLE_LEAD = "lead"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_VIEWER, "Viewer"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_LEAD, "Lead"),
        (ROLE_MEMBER, "Member"),
    ]

    node = models.ForeignKey(
        HierarchyNode,
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    user = models.ForeignKey(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="hierarchy_role_assignments",
    )
    role = models.CharField(
        max_length=64,
        choices=ROLE_CHOICES,
        default=ROLE_MANAGER,
    )
    inheritable = models.BooleanField(
        default=True,
        help_text="Whether this role propagates to child nodes via parent->permission",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "Hierarchy node role"
        verbose_name_plural = "Hierarchy node roles"
        constraints = [
            models.UniqueConstraint(
                fields=("node", "user", "role"),
                name="rebac_unique_hierarchy_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} is {self.role} on {self.node}"
