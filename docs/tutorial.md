# Tutorial: Building a Document Management System with django-spicedb

This tutorial walks you through building a document management system with fine-grained permissions using django-spicedb. By the end, you'll understand how to:

- Model relationships between users and resources
- Define permissions that inherit through hierarchies
- Check permissions in views
- Query only the objects a user can access

We'll build a system where:
- Users can create **folders** and **documents**
- Folders can contain other folders (nested hierarchy)
- Documents live in folders
- Permissions flow down: if you can view a folder, you can view everything inside it

---

## Part 1: Setup

### Prerequisites

- Python 3.11+
- Docker (for SpiceDB)
- A Django project

### Install django-spicedb

```bash
pip install django-spicedb
```

Add to your `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    'django_rebac',
]
```

### Start SpiceDB

SpiceDB is the authorization engine that stores and evaluates permissions. Start it with Docker:

```bash
docker run -d \
  --name spicedb \
  -p 50051:50051 \
  authzed/spicedb serve \
  --grpc-preshared-key "your-secret-key"
```

### Configure django-spicedb

Add to your `settings.py`:

```python
REBAC = {
    'adapter': {
        'endpoint': 'localhost:50051',
        'token': 'your-secret-key',
        'insecure': True,  # Use False in production with TLS
    },
}
```

---

## Part 2: Your First ReBAC Model

### Understanding the Problem

In traditional Django permissions, you might check:
```python
if user.has_perm('documents.view_document'):
    # User can view ALL documents
```

But what if Alice should only see documents in the "Engineering" folder, while Bob can see documents in "Marketing"? That's where ReBAC comes in.

### Creating the Document Model

Let's start simple - a document with an owner:

```python
# documents/models.py
from django.db import models
from django.conf import settings
from django_rebac.models import RebacModel

class Document(RebacModel):
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_documents',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class RebacMeta:
        relations = {
            'owner': 'owner',  # Maps the 'owner' relation to the 'owner' field
        }
        permissions = {
            'view': 'owner',   # Owner can view
            'edit': 'owner',   # Owner can edit
            'delete': 'owner', # Owner can delete
        }

    def __str__(self):
        return self.title
```

**What's happening here?**

1. `RebacModel` - Base class that adds permission methods to your model
2. `RebacMeta` - Like Django's `Meta`, but for permissions
3. `relations` - Declares named relationships. Here, `owner` points to whoever is in the `owner` field
4. `permissions` - Declares what each relation can do. `'view': 'owner'` means "the owner can view"

### Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### Publish the Schema

This compiles your `RebacMeta` definitions into SpiceDB's schema language and publishes it:

```bash
python manage.py publish_rebac_schema
```

You'll see output like:
```
Publishing schema to SpiceDB...
definition user {}
definition document {
    relation owner: user
    permission view = owner
    permission edit = owner
    permission delete = owner
}
Schema published successfully.
```

### Test It Out

```python
from django.contrib.auth import get_user_model
from documents.models import Document

User = get_user_model()

# Create users
alice = User.objects.create_user('alice', password='password')
bob = User.objects.create_user('bob', password='password')

# Alice creates a document
doc = Document.objects.create(
    title='Project Proposal',
    content='...',
    owner=alice,
)

# Check permissions
doc.has_perm(alice, 'view')   # True - Alice is the owner
doc.has_perm(alice, 'edit')   # True
doc.has_perm(bob, 'view')     # False - Bob is not the owner
```

**Key insight**: When you saved the document, django-spicedb automatically wrote a "tuple" to SpiceDB:
```
document:1#owner@user:1
```
This means "document 1 has owner user 1 (alice)".

---

## Part 3: Adding Hierarchy with Folders

Now let's add folders. The interesting part: permissions should flow down. If you can view a folder, you should be able to view all documents inside it.

### Creating the Folder Model

```python
# documents/models.py
class Folder(RebacModel):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_folders',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subfolders',
    )

    class RebacMeta:
        relations = {
            'owner': 'owner',
            'parent': 'parent',  # Self-referential for nested folders
        }
        permissions = {
            'view': 'owner + parent->view',
            'edit': 'owner + parent->edit',
        }

    def __str__(self):
        return self.name
```

**New concept: `parent->view`**

The expression `'view': 'owner + parent->view'` means:
- You can view this folder if you're the `owner`
- **OR** if you have `view` permission on the `parent` folder

This is permission inheritance! It flows up the tree automatically.

### Update Document to Use Folders

```python
class Document(RebacModel):
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_documents',
    )
    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        related_name='documents',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class RebacMeta:
        relations = {
            'owner': 'owner',
            'parent': 'folder',  # Document's parent is its folder
        }
        permissions = {
            'view': 'owner + parent->view',
            'edit': 'owner + parent->edit',
            'delete': 'owner',
        }
```

### Republish and Backfill

```bash
python manage.py publish_rebac_schema
python manage.py rebac_backfill  # Syncs existing data to SpiceDB
```

### Test the Hierarchy

```python
# Alice creates a folder structure
engineering = Folder.objects.create(name='Engineering', owner=alice)
specs = Folder.objects.create(name='Specs', owner=alice, parent=engineering)

# Alice creates a document in the nested folder
doc = Document.objects.create(
    title='API Spec',
    owner=alice,
    folder=specs,
)

# Alice can view everything (she's the owner)
engineering.has_perm(alice, 'view')  # True
specs.has_perm(alice, 'view')        # True
doc.has_perm(alice, 'view')          # True

# Bob can't view anything
doc.has_perm(bob, 'view')            # False
```

---

## Part 4: Sharing with Teams

Real apps need sharing. Let's add the ability to share folders with other users.

### Adding Viewers to Folders

```python
class Folder(RebacModel):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_folders',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subfolders',
    )
    viewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='viewable_folders',
    )

    class RebacMeta:
        relations = {
            'owner': 'owner',
            'parent': 'parent',
            'viewer': 'viewers',  # M2M field
        }
        permissions = {
            'view': 'owner + viewer + parent->view',
            'edit': 'owner + parent->edit',
        }
```

**What changed?**
- Added `viewers` M2M field
- Added `viewer` relation mapping to `viewers`
- Updated `view` permission: `'owner + viewer + parent->view'`

Now anyone in the `viewers` list can view the folder AND everything inside it (because documents inherit `parent->view`).

### Test Sharing

```python
# Alice shares Engineering folder with Bob
engineering.viewers.add(bob)

# Now Bob can view the folder and everything inside
engineering.has_perm(bob, 'view')  # True
specs.has_perm(bob, 'view')        # True (inherits from parent)
doc.has_perm(bob, 'view')          # True (inherits from folder)

# But Bob still can't edit
engineering.has_perm(bob, 'edit')  # False
```

---

## Part 5: Querying Accessible Objects

Checking one object at a time works, but what about listing all documents a user can see?

### Using RebacManager

```python
from django_rebac.integrations.orm import RebacManager

class Document(RebacModel):
    # ... fields ...

    objects = RebacManager()  # Add this line

    # ... RebacMeta ...
```

Now you can query:

```python
# Get all documents Alice can view
Document.objects.accessible_by(alice, 'view')

# Get all documents Bob can view
Document.objects.accessible_by(bob, 'view')

# Chain with other filters
Document.objects.accessible_by(alice, 'view').filter(
    created_at__gte=last_week
)
```

### Using in Views

```python
# views.py
from django.views.generic import ListView
from .models import Document

class DocumentListView(ListView):
    model = Document
    template_name = 'documents/list.html'

    def get_queryset(self):
        return Document.objects.accessible_by(
            self.request.user,
            'view'
        )
```

---

## Part 6: Groups and Roles

For larger apps, you often want role-based access: "Engineering team members can view, managers can edit."

### Creating a Group Model

```python
class Team(RebacModel):
    name = models.CharField(max_length=255)

    class RebacMeta:
        type_name = 'team'
        relations = {
            'member': {'subject': 'user'},   # Manual relation
            'manager': {'subject': 'user'},  # Manual relation
        }
        permissions = {
            'view': 'member + manager',
            'manage': 'manager',
        }


class TeamMembership(models.Model):
    """Through table with roles."""
    ROLE_MEMBER = 'member'
    ROLE_MANAGER = 'manager'
    ROLE_CHOICES = [
        (ROLE_MEMBER, 'Member'),
        (ROLE_MANAGER, 'Manager'),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)

    class Meta:
        unique_together = ('team', 'user')
```

**Manual relations**: When you use `{'subject': 'user'}` instead of a field name, you're telling django-spicedb "I'll sync this myself." This is for cases like role-based membership where the relation depends on a field value (the role), not just the existence of a row.

### Syncing Memberships

Create signal handlers to sync memberships:

```python
# signals.py
from django.db import transaction
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django_rebac.adapters import factory
from django_rebac.adapters.base import TupleKey, TupleWrite

@receiver(pre_save, sender=TeamMembership)
def track_old_role(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = TeamMembership.objects.get(pk=instance.pk)
            instance._old_role = old.role
            instance._old_team_id = old.team_id
            instance._old_user_id = old.user_id
        except TeamMembership.DoesNotExist:
            pass

@receiver(post_save, sender=TeamMembership)
def sync_membership_save(sender, instance, created, **kwargs):
    def do_sync():
        adapter = factory.get_adapter()

        # Delete old tuple if role/team/user changed
        if not created and hasattr(instance, '_old_role'):
            adapter.delete_tuples([TupleKey(
                object=f'team:{instance._old_team_id}',
                relation=instance._old_role,
                subject=f'user:{instance._old_user_id}',
            )])

        # Write new tuple
        adapter.write_tuples([TupleWrite(key=TupleKey(
            object=f'team:{instance.team_id}',
            relation=instance.role,
            subject=f'user:{instance.user_id}',
        ))])

    transaction.on_commit(do_sync)

@receiver(post_delete, sender=TeamMembership)
def sync_membership_delete(sender, instance, **kwargs):
    def do_delete():
        factory.get_adapter().delete_tuples([TupleKey(
            object=f'team:{instance.team_id}',
            relation=instance.role,
            subject=f'user:{instance.user_id}',
        )])

    transaction.on_commit(do_delete)
```

Register in your app config:

```python
# apps.py
from django.apps import AppConfig

class DocumentsConfig(AppConfig):
    name = 'documents'

    def ready(self):
        import documents.signals  # noqa
```

### Using Teams with Folders

```python
class Folder(RebacModel):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, ...)
    parent = models.ForeignKey('self', ...)
    team = models.ForeignKey(Team, null=True, blank=True, ...)

    class RebacMeta:
        relations = {
            'owner': 'owner',
            'parent': 'parent',
            'team': 'team',  # Link to team
        }
        permissions = {
            'view': 'owner + team->view + parent->view',
            'edit': 'owner + team->manage + parent->edit',
        }
```

Now:
- Team **members** can view folders assigned to their team
- Team **managers** can edit folders assigned to their team
- Permissions still inherit down through the folder hierarchy

---

## Part 7: Checking Permissions in Views

### The `can()` Function

For quick checks in views:

```python
from django_rebac.runtime import can

def document_detail(request, pk):
    doc = get_object_or_404(Document, pk=pk)

    if not can(request.user, 'view', doc):
        raise PermissionDenied

    return render(request, 'document.html', {'doc': doc})
```

### Using `has_perm()` on Models

```python
def document_edit(request, pk):
    doc = get_object_or_404(Document, pk=pk)

    if not doc.has_perm(request.user, 'edit'):
        raise PermissionDenied

    # ... handle edit ...
```

### In Templates

```html
{% if doc.has_perm(request.user, 'edit') %}
    <a href="{% url 'document-edit' doc.pk %}">Edit</a>
{% endif %}
```

---

## Summary

You've learned:

1. **Relations** map Django fields to named edges in the permission graph
2. **Permissions** compose relations with `+` (OR) and `->` (inherit)
3. **Inheritance** flows through `parent->permission` expressions
4. **M2M fields** automatically sync when you `.add()` or `.remove()`
5. **Manual relations** let you control syncing for complex cases like roles
6. **`accessible_by()`** efficiently queries objects a user can access
7. **`has_perm()`** and **`can()`** check individual permissions

The key mental model: **every save creates tuples, every check queries the graph**.

---

## Next Steps

- Read the [API Reference](./api-reference.md) for all configuration options
- See [Advanced Patterns](./advanced.md) for caveats, caching, and multi-tenancy
- Check the [example project](../example_project/) for a complete working app
