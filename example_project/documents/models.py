from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models

from django_rebac.core import register_type
from django_rebac.integrations.orm import RebacManager
from django_rebac.models import RebacModel, Resource


# Register Django's User model as a ReBAC type
User = get_user_model()
register_type(User, type_name="user")


class Company(models.Model):
    """Sample tenant model for multi-tenant testing."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=128, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Company"
        verbose_name_plural = "Companies"

    def __str__(self) -> str:
        return self.name


class Workspace(RebacModel):
    name = models.CharField(max_length=128)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True)

    class RebacMeta:
        relations = {
            "member": "members",
        }
        permissions = {
            "view": "member",
        }

    def __str__(self) -> str:
        return self.name


class Folder(RebacModel):
    """A folder that can contain documents."""
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_folders",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subfolders",
    )

    class RebacMeta:
        relations = {
            "owner": "owner",
            "parent": "parent",
        }
        permissions = {
            "view": "owner + parent->view",
            "edit": "owner + parent->edit",
        }

    def __str__(self) -> str:
        return self.name


class Document(RebacModel):
    title = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_documents",
    )
    folder = models.ForeignKey(
        Folder,
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

    class RebacMeta:
        relations = {
            "owner": "owner",
            "parent": "folder",
        }
        permissions = {
            "view": "owner + parent->view",
            "edit": "owner + parent->edit",
        }

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

    class RebacMeta:
        relations = {
            "parent": "parent",
            "manager": "managers",
        }
        permissions = {
            "view": "manager + parent->view",
            "manage": "manager + parent->manage",
        }

    def __str__(self) -> str:  # pragma: no cover - simple display helper
        base = super().__str__()
        return base or f"HierarchyResource:{self.pk}"


# =============================================================================
# Group-based Access Control (our own Group, not Django's auth.Group)
# =============================================================================


class Group(RebacModel):
    """
    A group of users with role-based membership.

    This is our own Group model for ReBAC, separate from Django's auth.Group.
    Django's auth.Group is for Django's permission system; this is for SpiceDB.

    Members are assigned via GroupMembership with roles (member/manager).
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=128, unique=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RebacManager()

    class Meta:
        verbose_name = "Group"
        verbose_name_plural = "Groups"

    class RebacMeta:
        type_name = "group"
        relations = {
            # Manual relations - synced via GroupMembership signals
            "member": {"subject": "user"},
            "manager": {"subject": "user"},
        }
        permissions = {
            "view": "member + manager",
            "manage": "manager",
        }

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class GroupMembership(models.Model):
    """
    Through table for Group membership with roles.

    Roles:
      - member: Can view resources in the group
      - manager: Can view and manage resources in the group

    Signal handlers sync this to SpiceDB tuples:
      - group:X#member@user:Y
      - group:X#manager@user:Y
    """

    ROLE_MEMBER = "member"
    ROLE_MANAGER = "manager"
    ROLE_CHOICES = [
        (ROLE_MEMBER, "Member"),
        (ROLE_MANAGER, "Manager"),
    ]

    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="group_memberships",
    )
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default=ROLE_MEMBER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Group membership"
        verbose_name_plural = "Group memberships"
        constraints = [
            models.UniqueConstraint(
                fields=("group", "user"),
                name="unique_group_membership",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} is {self.role} of {self.group}"


class Verification(RebacModel):
    """
    A resource that belongs to a Group.

    Permissions are inherited from the parent group:
      - Group members can view
      - Group managers can view + manage

    This is the idiomatic ReBAC pattern: resource → parent (group) → inherit permissions.
    """

    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=[
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
        ],
        default="pending",
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_verifications",
    )

    # Our Group model, not Django's auth.Group
    group = models.ForeignKey(
        Group,
        on_delete=models.CASCADE,
        related_name="verifications",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    objects = RebacManager()

    class RebacMeta:
        type_name = "verification"
        relations = {
            "owner": "owner",
            "parent": "group",
        }
        permissions = {
            "view": "owner + parent->view",
            "manage": "owner + parent->manage",
        }

    def __str__(self) -> str:
        return self.title
