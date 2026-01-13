# django-spicedb

Declarative, relationship-based access control (ReBAC) for Django, backed by [SpiceDB](https://authzed.com/spicedb). Define your authorization model once in Python; let Django enforce it everywhere.

---

## Features

- **Model-centric configuration** - Define relations and permissions directly on Django models via `RebacMeta`
- **Automatic tuple sync** - FK and M2M changes automatically sync to SpiceDB via signals
- **Permission inheritance** - Build hierarchies with `parent->permission` expressions
- **Group-based access** - Role-based group membership (member/manager) out of the box
- **Query integration** - Filter querysets by permission with `.accessible_by(user, 'view')`
- **FK change tracking** - Automatically cleans up stale tuples when relationships change

---

## Installation

```bash
pip install django-spicedb
```

Add to `INSTALLED_APPS`:
```python
INSTALLED_APPS = [
    # ...
    'django_rebac',
]
```

Configure SpiceDB connection:
```python
REBAC = {
    'adapter': {
        'endpoint': 'localhost:50051',
        'token': 'your-spicedb-token',
        'insecure': True,  # For local development
    },
}
```

---

## Quickstart

This walkthrough models a tiny system and shows the thinking process
you'll repeat in real apps: **rules → relations → permissions → code**.

### 0. Start SpiceDB

```bash
docker run -d --name spicedb -p 50051:50051 \
  authzed/spicedb serve --grpc-preshared-key devkey
```

### 1. Write the rules in plain English

Pick a concrete example. We'll use folders and documents:

- A folder can have a parent folder.
- A document has an owner and can live in a folder.
- Owners can view/edit their own items.
- If you can view/edit a parent folder, you can view/edit its children.

If you can explain the rule to a teammate, you can model it.

### 2. Turn rules into relations and permissions

Think in two layers:

- **Relations**: direct links like "document.owner" or "folder.parent"
- **Permissions**: expressions like "view = owner + parent->view"

For our example:

- Relations: `owner`, `parent`
- Permissions: `view = owner + parent->view`, `edit = owner + parent->edit`

### 3. Implement models with `RebacMeta`

Now we express that mapping in Django models.

```python
from django.db import models
from django_rebac.models import RebacModel
from django_rebac.integrations.orm import RebacManager

class Folder(RebacModel):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE)

    objects = RebacManager()

    class RebacMeta:
        relations = {
            'owner': 'owner',
            'parent': 'parent',
        }
        permissions = {
            'view': 'owner + parent->view',
            'edit': 'owner + parent->edit',
        }

class Document(RebacModel):
    title = models.CharField(max_length=255)
    owner = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    folder = models.ForeignKey('Folder', on_delete=models.CASCADE, null=True)

    objects = RebacManager()

    class RebacMeta:
        relations = {
            'owner': 'owner',
            'parent': 'folder',
        }
        permissions = {
            'view': 'owner + parent->view',
            'edit': 'owner + parent->edit',
        }
```

### 4. Publish schema and backfill tuples

Schema tells SpiceDB what the types and permissions look like.
Backfill creates the initial tuples from existing rows.

```bash
python manage.py publish_rebac_schema
python manage.py rebac_backfill
```

### 5. Use permissions in code

Now you can ask SpiceDB whether a user can access an object, or
filter querysets by permission.

```python
from django_rebac.runtime import can

if can(request.user, 'view', document):
    # User can view this document

documents = Document.objects.accessible_by(request.user, 'view')
```

---

## Group-Based Access Control

For team/department-based permissions, use the Group pattern:

```python
from django.db import models
from django_rebac.models import RebacModel
from django_rebac.integrations.orm import RebacManager

class Group(RebacModel):
    """A group with role-based membership."""
    name = models.CharField(max_length=255)

    objects = RebacManager()

    class RebacMeta:
        type_name = 'group'
        relations = {
            # Manual relations - no field binding, synced via GroupMembership
            'member': {'subject': 'user'},
            'manager': {'subject': 'user'},
        }
        permissions = {
            'view': 'member + manager',
            'manage': 'manager',
        }


class GroupMembership(models.Model):
    """Through table for group membership with roles."""
    ROLE_MEMBER = 'member'
    ROLE_MANAGER = 'manager'
    ROLE_CHOICES = [
        (ROLE_MEMBER, 'Member'),
        (ROLE_MANAGER, 'Manager'),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default=ROLE_MEMBER)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('group', 'user'), name='unique_membership'),
        ]


class Verification(RebacModel):
    """A resource that inherits permissions from its parent group."""
    title = models.CharField(max_length=255)
    owner = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    objects = RebacManager()

    class RebacMeta:
        type_name = 'verification'
        relations = {
            'owner': 'owner',
            'parent': 'group',
        }
        permissions = {
            'view': 'owner + parent->view',    # Owner OR group members
            'manage': 'owner + parent->manage', # Owner OR group managers
        }
```

Then create signal handlers for `GroupMembership` to sync tuples:

```python
# signals.py
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django_rebac.adapters import factory
from django_rebac.adapters.base import TupleKey, TupleWrite

def handle_membership_save(sender, instance, **kwargs):
    def do_sync():
        factory.get_adapter().write_tuples([
            TupleWrite(key=TupleKey(
                object=f'group:{instance.group_id}',
                relation=instance.role,
                subject=f'user:{instance.user_id}',
            ))
        ])
    transaction.on_commit(do_sync)

def handle_membership_delete(sender, instance, **kwargs):
    def do_delete():
        factory.get_adapter().delete_tuples([
            TupleKey(
                object=f'group:{instance.group_id}',
                relation=instance.role,
                subject=f'user:{instance.user_id}',
            )
        ])
    transaction.on_commit(do_delete)

post_save.connect(handle_membership_save, sender=GroupMembership)
post_delete.connect(handle_membership_delete, sender=GroupMembership)
```

Now permissions flow naturally:
- Group members can **view** all verifications in their group
- Group managers can **view and manage** all verifications in their group
- Owners always have full access to their own verifications

---

## RebacMeta Reference

### Relations

Map Django fields to SpiceDB relations:

```python
class RebacMeta:
    relations = {
        # FK binding - field name maps to relation
        'owner': 'owner_field',

        # M2M binding - field name maps to relation
        'member': 'members_field',

        # Manual relation - no field, synced manually
        'manager': {'subject': 'user'},

        # Parent relation for hierarchy
        'parent': 'parent_folder',
    }
```

### Permissions

SpiceDB permission expressions:

```python
class RebacMeta:
    permissions = {
        'view': 'owner + member',           # OR: owner or member
        'edit': 'owner',                     # Direct relation
        'admin': 'owner + parent->admin',   # Inherited from parent
        'manage': 'manager + parent->manage',
    }
```

### Binding Kinds

Bindings are auto-inferred from field types:
- **FK fields** → `kind: 'fk'` - Uses `field_id` cache, tracks changes
- **M2M fields** → `kind: 'm2m'` - Syncs on `post_add`, `post_remove`, `post_clear`
- **Manual** → `{'subject': 'type'}` - No auto-sync, handle via signals

---

## How It Works

1. **Schema Generation**: `RebacMeta` on models compiles to SpiceDB schema DSL
2. **Tuple Sync**: Django signals (`post_save`, `post_delete`, `m2m_changed`) write/delete tuples
3. **FK Tracking**: `pre_save` captures old FK values; `post_save` deletes stale tuples
4. **Transaction Safety**: All SpiceDB writes happen in `transaction.on_commit()`
5. **Permission Checks**: `can()` and `.accessible_by()` query SpiceDB via gRPC

---

## Management Commands

```bash
# Publish schema to SpiceDB
python manage.py publish_rebac_schema

# Backfill tuples from existing Django data
python manage.py rebac_backfill
```

---

## DRF Integration

```python
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['django_rebac.drf.ReBACPermission'],
}
```

---

## Full Tutorial

Want a complete walkthrough? **[Read the tutorial](docs/tutorial.md)** - builds a document management system step-by-step, explaining every concept along the way.

---

## Development

See [developers.md](developers.md) for development setup, testing, and contributing guidelines.

```bash
# Install dependencies
poetry install

# Start SpiceDB
docker compose up -d spicedb

# Run tests
poetry run pytest
```
