# Subsystem Test Matrix

Use this matrix to run the smallest useful test set for touched internals.

## Core registration/config

Files:

- `django_spicedb/core.py`
- `django_spicedb/conf.py`
- `django_spicedb/models/base.py`

Run:

```bash
pytest -q tests/test_conf.py tests/test_conf_edge_cases.py tests/test_checks.py
```

## Type graph and schema

Files:

- `django_spicedb/types/graph.py`
- `django_spicedb/schema.py`

Run:

```bash
pytest -q tests/test_type_graph.py tests/test_schema.py
```

## Sync pipeline

Files:

- `django_spicedb/sync/registry.py`
- `django_spicedb/sync/backfill.py`
- `django_spicedb/sync/reconcile.py`

Run:

```bash
pytest -q tests/test_sync.py tests/test_signal_edge_cases.py tests/test_through_bindings.py tests/test_through_edge_cases.py
```

## Runtime/evaluator/queryset integration

Files:

- `django_spicedb/runtime/evaluator.py`
- `django_spicedb/integrations/orm.py`

Run:

```bash
pytest -q tests/test_runtime.py tests/test_performance_correctness.py tests/test_security.py
```

## Adapter/factory

Files:

- `django_spicedb/adapters/base.py`
- `django_spicedb/adapters/spicedb.py`
- `django_spicedb/adapters/factory.py`

Run:

```bash
pytest -q tests/test_factory.py tests/test_spicedb_adapter.py
```

## Hierarchy/tenant/view integration

Files:

- `django_spicedb/tenant.py`
- `django_spicedb/models/hierarchy.py`
- `django_spicedb/views.py`
- `django_spicedb/hierarchy/signals.py`

Run:

```bash
pytest -q tests/test_hierarchy_integration.py tests/test_hierarchy_spicedb.py tests/test_hierarchy_views.py tests/test_hierarchy_advanced.py
```

## Group/verification path

Run:

```bash
pytest -q tests/test_group_verification.py tests/test_group_verification_spicedb.py
```

## Escalation rule for broader runs

If touching two or more subsystems, run both touched subsystem suites plus:

```bash
pytest -q tests/test_runtime.py tests/test_sync.py tests/test_security.py
```
