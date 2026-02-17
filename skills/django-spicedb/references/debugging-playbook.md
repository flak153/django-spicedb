# Debugging Playbook

Use this when authorization behavior is wrong and you need a deterministic investigation order.

## 1) Access Denied but Should Allow

Run checks in this order:

1. Subject type mapping:
- Verify `register_type(...)` exists for external subject model.
2. Object model mapping:
- Verify model inherits `RebacModel`.
- Verify `RebacMeta.relations` points to real fields/manual subjects.
3. Schema state:
- Recompile and republish schema after expression changes.
4. Tuple presence:
- Verify write path used sync-capable mutation method.
5. Expression logic:
- Validate inheritance chain (`parent->permission`) points to intended relation.
6. Tenant scope:
- Verify tenant context and tenant-aware filtering assumptions.

## 2) Access Allowed but Should Deny

1. Inspect permission expression for unintended unions.
2. Confirm relation writes are not over-broad (wrong FK/role mapping).
3. Confirm staff bypass policy behavior in hierarchy views.
4. Add targeted deny regression test before patching.

## 3) Through Roles Not Updating

1. Validate `RebacMeta.through` keys:
- `model`
- `object_fk`
- `subject_fk`
- `role_field`
- `roles`
2. Validate through model uses `RebacThroughManager` when bulk_create is used.
3. Replace raw through-table `QuerySet.update` with row `.save()` where correctness matters.
4. Run reconcile after large role migrations.

## 4) Queryset Results Wrong

1. Verify model manager supports `.accessible_by`.
2. Verify relation passed to `.accessible_by` is intended permission/relation.
3. Verify tenant pre-filtering when using tenant-aware queryset.
4. Confirm returned lookup IDs map to model PK type cleanly.

## 5) Drift Recovery Procedure

1. Run dry run:

```bash
python manage.py rebac_reconcile --dry-run
```

2. Run fix:

```bash
python manage.py rebac_reconcile --fix
```

3. Re-run failing allow/deny tests.

## 6) When to Escalate

Escalate from app integration to contributor-level investigation when:

1. Behavior appears inconsistent with intended documented library semantics.
2. Fix requires changing modules under `django_spicedb/`.
3. Reproduction exists in library test suites, not just app code.
