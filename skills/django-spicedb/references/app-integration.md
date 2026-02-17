# App Integration Playbook

Use this as the concrete build guide for integrating `django-spicedb` in real Django apps.

## Table of Contents

1. Integration checklist
2. Model templates
3. Permission expression cookbook
4. Runtime integration patterns
5. Mutation and sync-safe write patterns
6. Migration and rollout strategy
7. Test design checklist

## 1) Integration Checklist

1. Add `django_spicedb` to `INSTALLED_APPS`.
2. Configure `REBAC["adapter"]` settings.
3. Register subject type(s) you do not own, usually Django User.
4. Convert target models to `RebacModel`.
5. Add `RebacMeta.relations` and `RebacMeta.permissions`.
6. Set correct manager (`RebacManager`, `TenantAwareRebacManager`, `RebacThroughManager`).
7. Publish schema.
8. Backfill or reconcile tuples.
9. Add allow/deny tests for all key permissions.

## 2) Model Templates

### Template A: Owner + Parent Inheritance

```python
from django.db import models
from django.contrib.auth import get_user_model
from django_spicedb.models import RebacModel
from django_spicedb.integrations.orm import RebacManager
from django_spicedb.core import register_type

User = get_user_model()
register_type(User, type_name="user")


class Folder(RebacModel):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE)

    objects = RebacManager()

    class RebacMeta:
        relations = {
            "owner": "owner",
            "parent": "parent",
        }
        permissions = {
            "view": "owner + parent->view",
            "edit": "owner + parent->edit",
        }
```

### Template B: Resource Inheriting from Parent Group

```python
class Verification(RebacModel):
    title = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    group = models.ForeignKey("Group", on_delete=models.CASCADE)

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

### Template C: Through-Role Group Membership

```python
from django_spicedb.integrations.orm import RebacManager, RebacThroughManager


class Group(RebacModel):
    name = models.CharField(max_length=255)
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
    objects = RebacThroughManager()
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=32, choices=[("member", "Member"), ("manager", "Manager")])
```

### Template D: Tenant-Aware Hierarchy

Use tenant-aware manager and tenant context for access queries.
If you rely on optional hierarchy role signal module, connect it explicitly at startup.

## 3) Permission Expression Cookbook

### Direct owner access

```python
"view": "owner"
```

### Direct role access

```python
"view": "member + manager"
"manage": "manager"
```

### Recursive inheritance

```python
"view": "owner + parent->view"
```

### Hierarchical management chain

```python
"manage": "owner + manager + parent->manage"
```

### Exclusion/intersection cases

Use SpiceDB expression operators when your model requires strict combinations.
Validate these expressions with dedicated deny tests.

## 4) Runtime Integration Patterns

### Pattern 1: View-level guard

```python
from django_spicedb.runtime import can

if not can(request.user, "view", document):
    raise PermissionDenied
```

### Pattern 2: Object method

```python
if document.has_perm(request.user, "manage"):
    ...
```

### Pattern 3: List endpoint filtering

```python
qs = Document.objects.accessible_by(request.user, "view")
```

### Pattern 4: Contextual checks

```python
qs = Document.objects.accessible_by(
    request.user,
    "view",
    context={"scope": "branch"},
    consistency="fully_consistent",
    max_results=500,
)
```

## 5) Mutation and Sync-Safe Write Patterns

### Safe by default

1. `instance.save()`
2. FK assignment + save
3. M2M add/remove/clear
4. Through row create/save/delete

### Requires extra caution

1. `bulk_create`:
- Use custom managers for sync helpers.
2. `QuerySet.update`:
- May bypass signal-based assumptions for some scenarios.
3. Through-table role changes via raw `update`:
- Prefer row `.save()` or reconcile after update.

### Drift recovery

```bash
python manage.py rebac_reconcile --dry-run
python manage.py rebac_reconcile --fix
```

## 6) Migration and Rollout Strategy

### Phase 1: Introduce schema in shadow mode

1. Add models/relations/permissions.
2. Publish schema.
3. Reconcile tuples.
4. Keep old auth checks in place.

### Phase 2: Dual-read

1. Run both legacy check and `can(...)`.
2. Log mismatches.
3. Fix model relation gaps/expression bugs.

### Phase 3: Cutover

1. Replace legacy checks with `django-spicedb` checks.
2. Keep reconcile as operational safety net.
3. Monitor access anomalies and tuple drift.

## 7) Test Design Checklist

For each permission expression:

1. Direct allow test.
2. Direct deny test.
3. Inheritance allow test.
4. Inheritance deny test.
5. Role transition test (through models).
6. Tenant boundary test (if applicable).

For sync behavior:

1. FK change deletes old and writes new tuple.
2. M2M add/remove/clear sync verified.
3. Through role change delete/write verified.
4. Mutation path that bypasses sync is covered with reconcile fallback test.
