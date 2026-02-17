# Implementation Workflows

Use this guide when the task is "change the library internals safely."

## Table of Contents

1. Change planning pattern
2. Feature-specific workflows
3. Test targeting matrix
4. Safety checks before finishing

## 1) Change Planning Pattern

For every change:

1. Confirm behavior in code.
2. Confirm behavior in tests.
3. Identify one primary module to edit first.
4. Edit minimal surface area.
5. Run targeted tests.
6. Expand to broader tests only if needed.
7. Document behavior changes and caveats.

Prefer this order of reasoning:

1. `django_spicedb/core.py` and `django_spicedb/conf.py` for model/type setup.
2. `django_spicedb/types/graph.py` and `django_spicedb/schema.py` for schema semantics.
3. `django_spicedb/sync/registry.py` for tuple lifecycle.
4. `django_spicedb/runtime/evaluator.py` + `django_spicedb/integrations/orm.py` for check/query behavior.
5. `django_spicedb/adapters/` for SpiceDB API boundary.

## 2) Feature-Specific Workflows

### A) Add new binding behavior

Typical files:

- `django_spicedb/core.py`
- `django_spicedb/types/graph.py`
- `django_spicedb/sync/registry.py`

Steps:

1. Extend config extraction in `build_type_configs_from_registry()`.
2. Extend `TypeGraph` binding validation.
3. Extend tuple generation/signal handling in registry.
4. Add tests in `tests/test_sync.py` and binding edge-case suites.

### B) Add new permission evaluator capability

Typical files:

- `django_spicedb/runtime/evaluator.py`
- `django_spicedb/integrations/orm.py`

Steps:

1. Add evaluator API with conservative defaults.
2. Thread optional params through queryset helper if needed.
3. Keep existing method signatures backward compatible.
4. Add tests in `tests/test_runtime.py` and `tests/test_performance_correctness.py`.

### C) Change adapter behavior

Typical files:

- `django_spicedb/adapters/base.py`
- `django_spicedb/adapters/spicedb.py`
- `django_spicedb/adapters/factory.py`

Steps:

1. Preserve protocol shape if possible.
2. Update SpiceDBAdapter implementation.
3. Validate factory settings and error messages.
4. Run adapter/factory tests.

### D) Modify hierarchy/tenant access

Typical files:

- `django_spicedb/models/hierarchy.py`
- `django_spicedb/tenant.py`
- `django_spicedb/views.py`
- `django_spicedb/hierarchy/signals.py`

Steps:

1. Confirm tenant isolation behavior first.
2. Confirm staff bypass setting semantics.
3. Confirm role tuple sync hookup strategy (manual signal connection vs generic registry path).
4. Run hierarchy integration tests plus security checks.

## 3) Test Targeting Matrix

Use this matrix for fast validation:

- Type graph/schema edits:
  `tests/test_type_graph.py`, `tests/test_schema.py`, `tests/test_conf.py`
- Core registration/config extraction edits:
  `tests/test_conf.py`, `tests/test_checks.py`
- Sync registry edits:
  `tests/test_sync.py`, `tests/test_signal_edge_cases.py`, `tests/test_through_bindings.py`, `tests/test_through_edge_cases.py`
- Runtime/queryset edits:
  `tests/test_runtime.py`, `tests/test_performance_correctness.py`, `tests/test_security.py`
- Adapter/factory edits:
  `tests/test_spicedb_adapter.py`, `tests/test_factory.py`
- Hierarchy/tenant edits:
  `tests/test_hierarchy_integration.py`, `tests/test_hierarchy_spicedb.py`, `tests/test_hierarchy_views.py`, `tests/test_hierarchy_advanced.py`

## 4) Safety Checks Before Finishing

1. Verify no stale skill references remain:
- Skill name in frontmatter.
- `$django-spicedb` in prompt templates.
2. Re-run skill validation:
- `quick_validate.py skills/django-spicedb`
3. Confirm updated behavior section states:
- What changed.
- What did not change.
- Known limitations still present.
