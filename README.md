# django-spicedb

Declarative, relationship-based access control for Django, backed by [SpiceDB](https://authzed.com/spicedb). Describe your access graph once; let Django enforce it everywhere.

For development details, roadmap, and contributing guidelines, see [developers.md](developers.md).

---

## Installation

1. Install the package:
   ```bash
   pip install django-spicedb
   ```

2. Add to `INSTALLED_APPS` in `settings.py`:
   ```python
   INSTALLED_APPS = [
       # ...
       'django_rebac',
   ]
   ```

3. Configure SpiceDB connection in `settings.py` (example):
   ```python
   REBAC = {
       'ADAPTER': {
           'ENDPOINT': 'localhost:50051',
           'TOKEN': 'your-spicedb-token',
       },
   }
   ```

4. Run migrations:
   ```bash
   python manage.py migrate
   ```

---

## Quickstart

Assumptions: Python 3.11+, Docker for SpiceDB.

1. Start SpiceDB:
   ```bash
   docker run --name spicedb -p 50051:50051 authzed/spicedb serve --grpc-preshared-key your-token
   ```

2. Publish schema (compiles and applies to SpiceDB):
   ```bash
   python manage.py publish_rebac_schema
   ```

3. Backfill tuples:
   ```bash
   python manage.py rebac_backfill
   ```

4. Run your Django server:
   ```bash
   python manage.py runserver
   ```

Explore the admin at `/admin/` for types, grants, and access checks. Start in shadow mode (logs decisions without enforcing).

---

## Basic Usage

### Define Types and Permissions
Configure in `settings.py` or via admin:
```python
# Example type definition
REBAC['TYPES'] = {
    'project': {
        'relations': {'owner': 'user', 'member': 'user'},
        'permissions': {'view': 'owner | member'},
    },
}
```

### Check Permissions
```python
from django_rebac import can
from django_rebac.runtime import PermissionEvaluator

if can(request.user, 'view', project):
    # Allowed

evaluator = PermissionEvaluator(request.user)
if evaluator.can('edit', project):
    ...
```

### Query Accessible Objects
```python
from django_rebac.integrations import RebacManager

class Project(models.Model):
    ...
    objects = RebacManager()

Project.objects.accessible_by(request.user, 'view')
```

### Model Arbitrary Hierarchies
If you need ad-hoc parent/child relationships, you can use the built-in `ResourceNode` model:

```python
from django_rebac.models import ResourceNode

root = ResourceNode.objects.create(name="Head Office")
branch = ResourceNode.objects.create(name="Downtown", parent=root)
```

Add the corresponding entry to `REBAC['TYPES']`:

```python
REBAC['TYPES']['resource'] = {
    'model': 'django_rebac.models.ResourceNode',
    'relations': {'parent': 'resource'},
    'bindings': {'parent': {'field': 'parent', 'kind': 'fk'}},
}
```

Your SpiceDB schema can now define permissions that inherit along the `parent` relation:

```text
definition resource {
  relation parent: resource
  relation manager: user
permission manage = manager + parent->manage
}
```

#### Define Your Own Edges
Bind domain-specific models directly to relations:

```python
class Branch(models.Model):
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE)
    parent_branch = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    managers = models.ManyToManyField(User, related_name="branches_managed")
```

```python
REBAC['TYPES']['branch'] = {
    'model': 'core.models.Branch',
    'relations': {'parent': 'branch', 'manager': 'user'},
    'permissions': {'manage': 'manager + parent->manage'},
    'bindings': {
        'parent': {'field': 'parent_branch', 'kind': 'fk'},
        'manager': {'field': 'managers', 'kind': 'm2m'},
    },
}
```

FK bindings use the `<field>_id` cache so deletes avoid extra queries; M2M bindings emit tuples on `post_add`, `post_remove`, and `post_clear`. Mix and match `ResourceNode` with your own types—SpiceDB simply sees tuples.

### How REBAC Types Map to SpiceDB
- `settings.REBAC['types']` drives the TypeGraph. Each entry becomes a SpiceDB `definition` plus Django bindings.
- `relations`/`permissions` render into the SpiceDB DSL you would write manually.
- `bindings` describe how Django fields populate those relations (FK/M2M). TupleSync listens to model signals and writes/deletes tuples accordingly.
- Deployments compile and publish the schema (`publish_rebac_schema`) so Django and SpiceDB stay aligned.

Keep policy intent in the schema DSL, express bindings in Python/YAML, and django-spicedb handles the runtime bookkeeping.

### DRF Integration
```python
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['django_rebac.drf.ReBACPermission'],
}
```

For advanced features like caveats, grants, and HA setup, see [developers.md](developers.md).
