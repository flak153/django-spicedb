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

if can(request.user, 'view', project):
    # Allowed
```

### Query Accessible Objects
```python
Project.objects.accessible_by(request.user, 'view')
```

### DRF Integration
```python
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ['django_rebac.drf.ReBACPermission'],
}
```

For advanced features like caveats, grants, and HA setup, see [developers.md](developers.md).
