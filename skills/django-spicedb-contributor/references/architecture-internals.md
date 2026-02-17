# django-spicedb internals: contributor deep dive

Use this file when changing internals under `django_spicedb/`.
Use `$django-spicedb` skill for app integration tasks.
Base all conclusions on repository code and tests, not README/tutorial text.

## Table of Contents

1. Scope and source of truth
2. High-level request flow
3. Model registration and type graph build
4. Schema compilation and publication
5. Tuple synchronization internals
6. Runtime permission checks and queryset filtering
7. Tenant and hierarchy behavior
8. Operational workflows in this repo
9. Known implementation gaps and caveats
10. Fast debugging checklists

## 1) Scope and Source of Truth

Primary code paths:

- `django_spicedb/models/base.py`
- `django_spicedb/core.py`
- `django_spicedb/conf.py`
- `django_spicedb/types/graph.py`
- `django_spicedb/schema.py`
- `django_spicedb/sync/registry.py`
- `django_spicedb/runtime/evaluator.py`
- `django_spicedb/integrations/orm.py`
- `django_spicedb/adapters/spicedb.py`
- `example_project/documents/models.py`

Primary reality-check tests:

- `tests/test_runtime.py`
- `tests/test_sync.py`
- `tests/test_through_bindings.py`
- `tests/test_signal_edge_cases.py`
- `tests/test_group_verification_spicedb.py`
- `tests/test_hierarchy_spicedb.py`
- `tests/test_security.py`

## 2) High-Level Request Flow

### Startup and registry wiring

1. Django app boots `DjangoSpicedbConfig.ready()` in `django_spicedb/apps.py`.
2. It imports signals/checks, resets cached graph, then calls `registry.refresh()`.
3. `registry.refresh()` rebuilds signal handlers from the current type graph.

### Type graph generation

1. Any model inheriting `RebacModel` is auto-registered by metaclass (`RebacModelBase`).
2. `core.build_type_configs_from_registry()` inspects each model's `RebacMeta`.
3. `conf.get_type_graph()` instantiates `TypeGraph` from those configs.
4. `TypeGraph` validates:
- Parent existence/cycles
- Relation subject types
- Permission expression tokens
- Binding validity (`fk`, `m2m`, `through`, `manual`)

### Runtime authorization path

1. App code calls `can(subject, relation, obj)` or `QuerySet.accessible_by(...)`.
2. `PermissionEvaluator` normalizes references and calls adapter methods.
3. Adapter (`SpiceDBAdapter`) issues gRPC calls (`CheckPermission`, `LookupResources`).

### Sync path

1. Signals and manager hooks compute tuple writes/deletes.
2. Sync is scheduled via `transaction.on_commit(...)`.
3. Adapter persists relationships to SpiceDB with `WriteRelationships`.

## 3) Model Registration and Type Graph Build

### How a model becomes a ReBAC type

- Inherit `RebacModel` (`django_spicedb/models/base.py`).
- Define `class RebacMeta` on concrete model.
- Metaclass auto-registers model in `_REBAC_MODEL_REGISTRY`.

For external models you do not own (such as Django User), call:

```python
from django_spicedb.core import register_type
register_type(User, type_name="user")
```

Example registration is in `example_project/documents/models.py`.

### RebacMeta shapes

`RebacMeta.relations` supports two forms:

1. Field-based auto-binding:

```python
relations = {
    "owner": "owner",      # FK
    "members": "members",  # M2M
}
```

2. Manual relation definition:

```python
relations = {
    "member": {"subject": "user"},
}
```

`RebacMeta.permissions` is expression syntax passed through to schema.

`RebacMeta.through` maps through-table roles to relations (see Group example).

### Through mapping expansion

In `core.build_type_configs_from_registry()`:

- Each `through.roles` entry produces a synthetic binding:
  `kind="through"` with role-specific metadata.
- These bindings are later used by registry through-table handlers and backfill/reconcile logic.

## 4) Schema Compilation and Publication

### Compile only

Use:

```python
import django_spicedb.conf as conf
graph = conf.get_type_graph()
schema = graph.compile_schema()
```

### Publish

Use:

```python
from django_spicedb.adapters import factory
from django_spicedb.schema import publish_schema
import django_spicedb.conf as conf

digest = publish_schema(factory.get_adapter(), graph=conf.get_type_graph())
```

Notes:

- Publication helper exists (`django_spicedb/schema.py`).
- This repository currently does not include dedicated management commands to publish schema or run generic backfill.
- `rebac_reconcile --fix` is the closest built-in operational sync tool.

## 5) Tuple Synchronization Internals

Main logic lives in `django_spicedb/sync/registry.py`.

### 5.1 Signal registry refresh

`registry.refresh()` does:

1. Disconnect prior handlers.
2. Load graph.
3. Register per-type handlers for models with bindings.
4. Register aggregated through-table handlers.

### 5.2 FK binding sync

For each FK binding:

- `pre_save` snapshots old values from DB.
- `post_save` computes tuple diff:
  - delete old tuple if FK changed
  - write new tuple for new state
- `post_delete` computes tuple key and deletes.
- Writes/deletes deferred to transaction commit.

### 5.3 M2M binding sync

Uses `m2m_changed` handlers:

- `post_add`: write tuples.
- `post_remove`: delete tuples.
- `pre_clear` + `post_clear`: snapshot IDs then delete tuples.

### 5.4 Through-table role sync

Through metadata comes from parent `RebacMeta.through`.
Registry aggregates role mappings per through model and installs handlers:

- `pre_save`: snapshot old object/subject/role.
- `post_save`: delete old tuple on change, write new tuple.
- `post_delete`: delete tuple for removed row.

### 5.5 bulk_create support

Implemented via custom managers in `django_spicedb/integrations/orm.py`:

- `RebacQuerySet.bulk_create()` -> `sync_instances(result)`
- `RebacThroughQuerySet.bulk_create()` -> `sync_through_instances(result)`

Important:

- Bulk sync only happens when model uses the custom manager.
- Raw bulk_create on a model with default manager bypasses this helper.

### 5.6 QuerySet.update support

`sync_queryset_update(queryset, **updated_fields)`:

- Snapshots old rows.
- Executes update.
- Re-reads rows.
- Computes FK tuple diffs.
- Schedules write/delete on commit.

Current limits:

- Primarily supports `subject_field == "pk"` path.
- Complex custom object/subject field resolution is intentionally limited.
- Raw `QuerySet.update()` on through tables is not automatically reconciled.

## 6) Runtime Permission Checks and Queryset Filtering

### PermissionEvaluator

`django_spicedb/runtime/evaluator.py`:

- Normalizes subject references from model instance or `type:id` string.
- Validates relation name format.
- Caches `can()` results per evaluator instance.
- Supports `batch_can()` and `lookup_resources(...)` with optional context and consistency.

Behavior details:

- `can()` catches adapter exceptions and returns `False` after logging.
- Cache is evaluator-instance scoped (not global).
- `lookup_resources(...)` accepts `max_results`.

### can(...) convenience function

`can(subject, relation, obj, ...)` constructs a new evaluator and calls `.can(...)`.

### Queryset filtering

`RebacQuerySet.accessible_by(...)`:

1. Calls evaluator lookup.
2. Parses returned IDs through pk field conversion.
3. Drops invalid IDs with warning.
4. Builds `pk__in` filters in chunks of 500 to avoid SQL variable limits.

Tenant-aware version:

- `TenantAwareRebacQuerySet.accessible_by(...)` first filters by current thread-local tenant, then applies permission-based filtering.

## 7) Tenant and Hierarchy Behavior

### Thread-local tenant context

`django_spicedb/tenant.py` provides:

- `tenant_context(...)`
- `get_current_tenant()`
- `TenantAwarePermissionEvaluator`

`TenantAwarePermissionEvaluator.can(...)` denies cross-tenant access before adapter check.

### Hierarchy models

`django_spicedb/models/hierarchy.py` includes:

- `HierarchyTypeDefinition`
- `HierarchyNode` (tenant-scoped, path/depth maintenance, tenant-aware manager)
- `HierarchyNodeRole` (role assignment table)

### Hierarchy role signal module

`django_spicedb/hierarchy/signals.py` directly syncs:

- parent tuples for node hierarchy
- role tuples for `HierarchyNodeRole`

Important:

- These hierarchy signals are not auto-connected by `DjangoSpicedbConfig.ready()`.
- Connect explicitly where needed:

```python
from django_spicedb.hierarchy import connect_hierarchy_signals
connect_hierarchy_signals()
```

### Hierarchy views and bypass mode

`django_spicedb/views.py` checks:

- `staff_bypass_permissions` from `REBAC` config, default `True`.
- If enabled, `is_staff` and `is_superuser` bypass permission checks in hierarchy views.

Set this explicitly in production policy decisions.

## 8) Operational Workflows in This Repo

### 8.1 Reconcile command

Available command:

```bash
python manage.py rebac_reconcile --dry-run
python manage.py rebac_reconcile --fix
python manage.py rebac_reconcile --type group --type verification --fix
```

### 8.2 Export policy

Available command:

```bash
python manage.py export_rebac_policy rebac_policy.yaml
```

### 8.3 Publish schema manually

No dedicated command currently. Use Django shell snippet from section 4.

### 8.4 Test suites to trust first

```bash
pytest -q tests/test_runtime.py tests/test_sync.py tests/test_through_bindings.py
pytest -q tests/test_group_verification_spicedb.py
pytest -q tests/test_hierarchy_spicedb.py
```

## 9) Known Implementation Gaps and Caveats

1. Reconcile stale detection is not implemented.
- `sync/reconcile.py` reports `stale=0` because adapter protocol lacks tuple read API.

2. Post-commit sync failures can create drift.
- Writes happen in `transaction.on_commit`.
- If adapter call fails after DB commit, model data and SpiceDB can diverge.

3. Through-table `QuerySet.update()` is not auto-synced.
- Use row-by-row `.save()` or run reconcile/fix flow afterwards.

4. Some tests/comments are stale relative to implementation.
- Example: code now supports `max_results` in evaluator and queryset APIs.
- Validate behavior against source code before repeating test commentary verbatim.

5. Hierarchy signal usage is optional/manual.
- If not connected, `HierarchyNodeRole` tuple sync depends on alternative logic you implement.

## 10) Fast Debugging Checklists

### Permission unexpectedly denied

1. Verify subject/object type mapping from `conf.get_type_for_model`.
2. Verify tuples are written by the expected signal/manager path.
3. Verify compiled permission expression and relation names.
4. Verify tenant context and bypass setting if hierarchy path is used.
5. Run reconcile in dry-run/fix mode and retest.

### Tuples unexpectedly missing

1. Confirm model uses `RebacManager` or `RebacThroughManager` if relying on bulk_create sync.
2. Confirm registry was refreshed after model/config changes.
3. Confirm through config `model/object_fk/subject_fk/role_field/roles` is complete.
4. Confirm operation was not raw `QuerySet.update()` on through table.

### Access unexpectedly broad in hierarchy UI/API

1. Check `REBAC["staff_bypass_permissions"]`.
2. Validate whether caller is `is_staff` or `is_superuser`.
3. Verify tenant scoping (content type + object id) in queryset filters.
