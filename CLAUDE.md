# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

django-spicedb is a declarative, relationship-based access control (ReBAC) library for Django, backed by SpiceDB. It bridges Django ORM models with a Zanzibar-style authorization engine, allowing developers to define relationships, roles, and permissions declaratively.

## Common Commands

```bash
# Install dependencies
poetry install

# Start SpiceDB + Postgres (Docker required)
docker compose up spicedb

# Run Django migrations
poetry run python manage.py migrate

# Publish REBAC schema to SpiceDB
poetry run python manage.py publish_rebac_schema

# Backfill tuples from Django models to SpiceDB
poetry run python manage.py rebac_backfill

# Run tests (auto-starts SpiceDB via Docker Compose)
poetry run pytest

# Run a single test file
poetry run pytest tests/test_type_graph.py

# Run a specific test
poetry run pytest tests/test_type_graph.py::test_function_name -v

# Lint and type check
poetry run ruff check
poetry run mypy django_rebac
```

## Architecture

### Package Structure (`django_rebac/`)

- **types/** - TypeGraph registry that validates configuration and compiles to SpiceDB schema DSL
  - `graph.py` - Core TypeGraph class with validation (parent cycles, relation subjects, permission expressions, bindings)

- **adapters/** - SpiceDB adapter layer
  - `base.py` - Protocol definition (`RebacAdapter`) with `check()`, `lookup_resources()`, `write_tuples()`, `delete_tuples()`, `publish_schema()`
  - `spicedb.py` - gRPC implementation for SpiceDB
  - `factory.py` - Adapter factory for dependency injection

- **sync/** - Tuple synchronization between Django and SpiceDB
  - `registry.py` - Watches `post_save`, `post_delete`, `m2m_changed` signals; emits tuple writes/deletes based on configured bindings
  - `backfill.py` - Batch backfill of tuples from existing Django data

- **runtime/** - Permission evaluation
  - `evaluator.py` - `PermissionEvaluator` class (request-scoped, batched checks, caching) and `can()` convenience function

- **integrations/** - Django/DRF integration points
  - `orm.py` - `RebacManager` and `RebacQuerySet` with `.accessible_by(user, relation)` method

- **conf.py** - Settings loader for `settings.REBAC`

### Key Concepts

1. **Types** map to Django models; defined in `settings.REBAC['types']`
2. **Relations** are named edges (FK/M2M bindings) from objects to subjects
3. **Permissions** are SpiceDB rewrite expressions composing relations (e.g., `view = owner | member | parent->view`)
4. **Bindings** declare how model fields map to relations (kind: `fk`, `m2m`, `through`, `manual`)
5. **TupleSync** automatically writes/deletes SpiceDB tuples when Django models change

### Configuration Example

```python
REBAC = {
    "types": {
        "user": {"model": "django.contrib.auth.models.User"},
        "document": {
            "model": "myapp.models.Document",
            "relations": {"owner": "user", "parent": "folder"},
            "permissions": {"view": "owner + parent->view"},
            "bindings": {
                "owner": {"field": "owner", "kind": "fk"},
                "parent": {"field": "folder", "kind": "fk"},
            },
        },
    },
    "adapter": {
        "endpoint": "localhost:50051",
        "token": "your-token",
        "insecure": True,
    },
}
```

### Testing

- **Unit tests**: Use `RecordingAdapter` fixture from `tests/conftest.py` for mocking SpiceDB
- **Integration tests**: Use `spicedb_adapter` fixture which auto-starts SpiceDB via Docker Compose
- Test settings use `example_project.settings` as `DJANGO_SETTINGS_MODULE`

### Example Project

`example_project/` contains a working Django project with:
- `documents/models.py` - Sample models with hierarchy (HierarchyResource, Document)
- `settings.py` - Complete REBAC configuration demonstrating FK/M2M bindings and permission inheritance