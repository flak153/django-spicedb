"""Multi-tenant hierarchy models."""

from __future__ import annotations

from django.db import models

from django_spicedb.integrations.orm import TenantAwareRebacManager

from .base import RebacModel


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
