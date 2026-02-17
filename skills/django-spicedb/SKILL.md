---
name: django-spicedb
description: Implement django-spicedb in Django application code. Use for translating authorization rules into RebacModel/RebacMeta definitions, choosing FK/M2M/through bindings, wiring runtime checks and queryset filtering, and handling schema publish and tuple sync safely.
---

# Django Spicedb

## Overview

Use this skill when the task is application integration of `django-spicedb`.
The target is Django app code: models, service layer, and runtime permission calls.

Do not use this skill for modifying internals under `django_spicedb/`; use `$django-spicedb-contributor` for that scope.

## How The Library Works

### Authorization pipeline

1. Models inheriting `RebacModel` are registered by `RebacModelBase`.
2. Optional external subject/resource models are registered with `register_type(...)`.
3. `RebacMeta` definitions are compiled into a type graph (`get_type_graph()`).
4. The type graph is compiled to SpiceDB schema and published with `publish_schema(...)`.
5. FK/M2M/through changes trigger tuple sync handlers.
6. Runtime checks are evaluated through `can(...)`, `.has_perm(...)`, and `.accessible_by(...)`.

### Binding semantics

1. FK binding: one row points to one related subject/resource.
2. M2M binding: many direct links with no role dimension.
3. Through binding: relation value is derived from a role field in a join table.

Use through bindings whenever role transitions must change authorization (`member` vs `manager`).

## Implementation Workflow

### 1) Gather inputs before coding

Collect these from the task/request:

1. subject types (`User`, `ServiceAccount`, `Group`)
2. protected resource types (`Document`, `Folder`, `Verification`)
3. direct relations (`owner`, `parent`, `member`, `manager`)
4. inheritance needs (`parent->view`, `workspace->edit`)
5. tenancy constraints (single tenant vs tenant-scoped checks)
6. write paths used by the app (`save`, M2M add/remove, through writes, `bulk_create`, `QuerySet.update`)

### 2) Convert business rules into relation/permission graph

Translate plain-English policy to type-level rules first.

Example translation:

1. "Owners can edit documents." -> relation `owner`, permission `edit = owner`
2. "Workspace managers can edit workspace documents." -> document relation to workspace, `edit` includes `workspace->edit`
3. "Folder access cascades to children." -> relation `parent`, permission includes `parent->view`

Keep permission expressions small and composable.

### 3) Implement models and `RebacMeta`

For each protected model:

1. inherit from `RebacModel`
2. add `objects = RebacManager()`
3. define `RebacMeta.type_name`, `relations`, and `permissions`
4. for role-based memberships, define `RebacMeta.through` and set through model manager to `RebacThroughManager()`

### 4) Publish schema after relation/permission changes

Use this command:

```bash
python manage.py shell -c "import django_spicedb.conf as conf; from django_spicedb.adapters import factory; from django_spicedb.schema import publish_schema; print(publish_schema(factory.get_adapter(), graph=conf.get_type_graph()))"
```

### 5) Wire runtime checks in service-layer boundaries

Use service functions as policy boundaries rather than spreading checks ad hoc in every view.

1. read endpoints: check `view`
2. mutation endpoints: check `edit` or `manage`
3. list endpoints: use `.accessible_by(...)` for server-side filtering

### 6) Keep write paths sync-safe

Preferred write paths:

1. `instance.save()`
2. M2M manager methods (`add`, `remove`, `clear`)
3. through-row create/save/delete with `RebacThroughManager`
4. manager `bulk_create` where sync helpers are supported

Use caution with `QuerySet.update` on authorization-relevant fields; use safer writes when possible.

### 7) Rollout discipline

1. publish schema before switching runtime checks
2. cut runtime guards over to `can`/`has_perm`/`accessible_by`
3. keep operational reconcile workflow documented for tuple drift recovery

## Worked Example 1: Tenant Workspace + Folder + Document

This pattern covers:

1. tenant-scoped workspace membership via through roles
2. folder inheritance
3. document inheritance from workspace and folder
4. service-layer runtime checks and queryset filtering

`models.py`

```python
from django.contrib.auth import get_user_model
from django.db import models

from django_spicedb.core import register_type
from django_spicedb.integrations.orm import RebacManager, RebacThroughManager
from django_spicedb.models import RebacModel

User = get_user_model()
register_type(User, type_name="user")


class Tenant(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=255)


class Workspace(RebacModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="workspaces")
    slug = models.SlugField(max_length=128)
    title = models.CharField(max_length=255)

    objects = RebacManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "slug"), name="uniq_workspace_per_tenant")
        ]

    class RebacMeta:
        type_name = "workspace"
        relations = {
            "member": {"subject": "user"},
            "manager": {"subject": "user"},
        }
        permissions = {
            "view": "member + manager",
            "edit": "manager",
        }
        through = {
            "model": "myapp.models.WorkspaceMembership",
            "object_fk": "workspace",
            "subject_fk": "user",
            "role_field": "role",
            "roles": {
                "member": "member",
                "manager": "manager",
            },
        }


class WorkspaceMembership(models.Model):
    ROLE_MEMBER = "member"
    ROLE_MANAGER = "manager"
    ROLE_CHOICES = [
        (ROLE_MEMBER, "Member"),
        (ROLE_MANAGER, "Manager"),
    ]

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)

    objects = RebacThroughManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("workspace", "user"), name="uniq_workspace_membership")
        ]


class Folder(RebacModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="folders")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_folders")
    name = models.CharField(max_length=255)

    objects = RebacManager()

    class RebacMeta:
        type_name = "folder"
        relations = {
            "owner": "owner",
            "workspace": "workspace",
            "parent": "parent",
        }
        permissions = {
            "view": "owner + workspace->view + parent->view",
            "edit": "owner + workspace->edit + parent->edit",
        }


class Document(RebacModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="documents")
    folder = models.ForeignKey(
        Folder,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_documents")
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)

    objects = RebacManager()

    class RebacMeta:
        type_name = "document"
        relations = {
            "owner": "owner",
            "workspace": "workspace",
            "parent": "folder",
        }
        permissions = {
            "view": "owner + workspace->view + parent->view",
            "edit": "owner + workspace->edit + parent->edit",
        }
```

`services.py`

```python
from django.core.exceptions import PermissionDenied
from django.db import transaction

from django_spicedb.runtime import can
from django_spicedb.tenant import tenant_context

from .models import Document, Workspace, WorkspaceMembership


def workspace_context(workspace: Workspace) -> dict:
    return {
        "tenant_id": str(workspace.tenant_id),
        "workspace_id": str(workspace.pk),
    }


def list_viewable_documents(actor, workspace: Workspace):
    ctx = workspace_context(workspace)
    return (
        Document.objects.filter(workspace=workspace)
        .accessible_by(actor, "view", context=ctx)
        .select_related("owner", "folder", "workspace")
    )


def read_document(actor, workspace: Workspace, document_id: int) -> Document:
    document = Document.objects.select_related("workspace", "folder").get(
        pk=document_id,
        workspace=workspace,
    )
    with tenant_context(str(workspace.tenant_id)):
        allowed = can(actor, "view", document, context=workspace_context(workspace))
    if not allowed:
        raise PermissionDenied("Missing document:view")
    return document


@transaction.atomic
def update_document_title(actor, workspace: Workspace, document_id: int, title: str) -> Document:
    document = Document.objects.select_for_update().get(pk=document_id, workspace=workspace)
    if not document.has_perm(actor, "edit", context=workspace_context(workspace)):
        raise PermissionDenied("Missing document:edit")
    document.title = title
    document.save(update_fields=["title"])
    return document


@transaction.atomic
def invite_workspace_members(actor, workspace: Workspace, user_ids: list[int]) -> None:
    if not workspace.has_perm(actor, "edit", context=workspace_context(workspace)):
        raise PermissionDenied("Missing workspace:edit")

    rows = [
        WorkspaceMembership(
            workspace=workspace,
            user_id=user_id,
            role=WorkspaceMembership.ROLE_MEMBER,
        )
        for user_id in user_ids
    ]
    WorkspaceMembership.objects.bulk_create(rows, ignore_conflicts=True)
```

## Worked Example 2: Group Membership Roles + Verification Workflow

This pattern covers:

1. group membership via through-role relation mapping
2. verification resources inheriting group permissions
3. role transitions affecting `manage`
4. service-layer checks for submit/approve/reject flows

`models.py`

```python
from django.contrib.auth import get_user_model
from django.db import models

from django_spicedb.core import register_type
from django_spicedb.integrations.orm import RebacManager, RebacThroughManager
from django_spicedb.models import RebacModel

User = get_user_model()
register_type(User, type_name="user")


class Group(RebacModel):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=255)

    objects = RebacManager()

    class RebacMeta:
        type_name = "group"
        relations = {
            "member": {"subject": "user"},
            "manager": {"subject": "user"},
        }
        permissions = {
            "view": "member + manager",
            "manage": "manager",
        }
        through = {
            "model": "myapp.models.GroupMembership",
            "object_fk": "group",
            "subject_fk": "user",
            "role_field": "role",
            "roles": {
                "member": "member",
                "manager": "manager",
            },
        }


class GroupMembership(models.Model):
    ROLE_MEMBER = "member"
    ROLE_MANAGER = "manager"
    ROLE_CHOICES = [
        (ROLE_MEMBER, "Member"),
        (ROLE_MANAGER, "Manager"),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_memberships")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)

    objects = RebacThroughManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("group", "user"), name="uniq_group_user_membership")
        ]


class Verification(RebacModel):
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="verifications")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_verifications")
    title = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)

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
```

`services.py`

```python
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import Group, GroupMembership, Verification


def list_visible_verifications(actor, group: Group):
    return (
        Verification.objects.filter(group=group)
        .accessible_by(actor, "view")
        .select_related("group", "owner")
    )


@transaction.atomic
def submit_verification(actor, group: Group, title: str, payload: dict) -> Verification:
    if not group.has_perm(actor, "view"):
        raise PermissionDenied("Missing group:view")
    return Verification.objects.create(
        group=group,
        owner=actor,
        title=title,
        payload=payload,
        status=Verification.STATUS_PENDING,
    )


def require_manage_access(actor, verification_id: int) -> Verification:
    verification = Verification.objects.select_related("group", "owner").get(pk=verification_id)
    if not verification.has_perm(actor, "manage"):
        raise PermissionDenied("Missing verification:manage")
    return verification


@transaction.atomic
def approve_verification(actor, verification_id: int) -> Verification:
    verification = require_manage_access(actor, verification_id)
    if verification.status != Verification.STATUS_PENDING:
        raise ValidationError("Only pending verifications can be approved")
    verification.status = Verification.STATUS_APPROVED
    verification.save(update_fields=["status"])
    return verification


@transaction.atomic
def reject_verification(actor, verification_id: int) -> Verification:
    verification = require_manage_access(actor, verification_id)
    if verification.status != Verification.STATUS_PENDING:
        raise ValidationError("Only pending verifications can be rejected")
    verification.status = Verification.STATUS_REJECTED
    verification.save(update_fields=["status"])
    return verification


@transaction.atomic
def set_group_role(actor, membership_id: int, new_role: str) -> GroupMembership:
    membership = GroupMembership.objects.select_related("group").get(pk=membership_id)
    if not membership.group.has_perm(actor, "manage"):
        raise PermissionDenied("Missing group:manage")
    membership.role = new_role
    membership.save(update_fields=["role"])
    return membership


@transaction.atomic
def bulk_add_group_members(actor, group: Group, user_ids: list[int]) -> None:
    if not group.has_perm(actor, "manage"):
        raise PermissionDenied("Missing group:manage")

    rows = [
        GroupMembership(group=group, user_id=user_id, role=GroupMembership.ROLE_MEMBER)
        for user_id in user_ids
    ]
    GroupMembership.objects.bulk_create(rows, ignore_conflicts=True)
```

## References
1. `references/how-it-works.md` for internals from an integrator perspective
2. `references/app-integration.md` for additional implementation patterns
3. `references/debugging-playbook.md` for incident triage
4. `references/test-playbook.md` for optional test strategy
5. `references/claude-codex-prompt-pack.md` for reusable prompts
