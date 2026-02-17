---
name: django-spicedb-contributor
description: Contributor workflow for developing and maintaining django-spicedb internals. Use for implementing features, fixing bugs, refactoring core modules, changing adapter/runtime/sync/type-graph behavior, and validating internal changes with targeted test selection while preserving API compatibility unless breaking changes are explicitly requested.
---

# Django Spicedb Contributor

## Overview

Use this skill only when work requires editing files under `django_spicedb/`.
For app-level integration, use `$django-spicedb`.

## Contributor Objectives

1. Fix root causes, not symptoms.
2. Keep public API stable by default.
3. Minimize blast radius of changes.
4. Use targeted tests before broad suites.
5. Document behavior changes and known caveats.

## Default Internal Workflow

1. Reproduce behavior in tests first.
2. Locate owning subsystem.
3. Patch minimal responsible module.
4. Add or update regression tests.
5. Validate with subsystem test matrix.
6. Expand to cross-cutting tests if needed.
7. Summarize compatibility impact.

## Subsystem Ownership Map

- Model registration/config extraction:
  `django_spicedb/models/base.py`, `django_spicedb/core.py`, `django_spicedb/conf.py`
- Type graph/schema:
  `django_spicedb/types/graph.py`, `django_spicedb/schema.py`
- Sync pipeline:
  `django_spicedb/sync/registry.py`, `django_spicedb/sync/backfill.py`, `django_spicedb/sync/reconcile.py`
- Runtime APIs:
  `django_spicedb/runtime/evaluator.py`, `django_spicedb/runtime/__init__.py`, `django_spicedb/integrations/orm.py`
- Adapter boundary:
  `django_spicedb/adapters/base.py`, `django_spicedb/adapters/spicedb.py`, `django_spicedb/adapters/factory.py`
- Tenant/hierarchy:
  `django_spicedb/tenant.py`, `django_spicedb/models/hierarchy.py`, `django_spicedb/views.py`, `django_spicedb/hierarchy/signals.py`

## Invariants to Preserve

1. `RebacModel` auto-registration behavior.
2. `TypeGraph` validation guarantees for parents/relations/permissions/bindings.
3. Adapter protocol semantics in `adapters/base.py`.
4. Evaluator subject/reference validation and cache semantics.
5. Sync tuple lifecycle across FK/M2M/through operations.

## Compatibility Rule

Default behavior:

1. Keep signatures and semantics stable for exported runtime APIs.
2. Keep manager/queryset method contracts stable unless breaking change is requested.
3. Keep adapter protocol backward compatible.

If breaking change is explicitly requested:

1. Identify affected call sites.
2. Provide migration notes.
3. Update tests and docs in same change.

## Change-Type Playbooks

### Add/modify binding kind behavior

1. Update extraction in `core.py`.
2. Update validation in `types/graph.py`.
3. Update sync generation/handlers in `sync/registry.py`.
4. Add sync + edge-case tests.

### Change evaluator/query behavior

1. Update `runtime/evaluator.py`.
2. Update queryset integrations in `integrations/orm.py`.
3. Validate context, consistency, and caching behavior.
4. Add runtime/performance/security regression tests.

### Change adapter behavior

1. Update `adapters/spicedb.py`.
2. Keep protocol alignment with `adapters/base.py`.
3. Validate factory config/errors in `adapters/factory.py`.
4. Run adapter/factory tests.

### Change tenant/hierarchy semantics

1. Confirm tenant isolation behavior first.
2. Confirm staff bypass semantics and policy intent.
3. Verify hierarchy signal strategy and lifecycle.
4. Run hierarchy integration + security suites.

## Completion Checklist

1. Behavior reproduced before patch.
2. Regression test added or updated.
3. Subsystem tests green.
4. Cross-cutting tests green where relevant.
5. Compatibility/migration impact documented.

## Resources

- Internal architecture deep dive:
  `references/architecture-internals.md`
- Implementation workflow patterns:
  `references/implementation-workflows.md`
- Subsystem test matrix:
  `references/subsystem-test-matrix.md`
- Compatibility policy:
  `references/api-compatibility.md`
- Release checklist:
  `references/release-checklist.md`
- Prompt templates:
  `references/contributor-prompt-pack.md`
