# How It Works (App Integrator View)

Use this reference to understand runtime behavior while integrating the library in app code.

## Table of Contents

1. Responsibility split
2. Internal pipeline from models to checks
3. Sync behavior by write operation
4. Permission query behavior
5. Tenant and hierarchy behavior
6. Operational realities and caveats
7. Symptom-to-cause matrix

## 1) Responsibility Split

### What your app owns

1. Model structure (FK/M2M/through tables).
2. `RebacMeta` relations and permission expressions.
3. Mutation patterns you use (`save`, `bulk_create`, `update`, etc.).
4. Runtime call sites (`can`, `has_perm`, `accessible_by`).

### What django-spicedb owns

1. Model registration and type graph compilation.
2. Schema compilation/publishing helpers.
3. Tuple sync signal registry and sync helpers.
4. Permission evaluator + queryset lookup logic.
5. Adapter calls to SpiceDB.

## 2) Internal Pipeline: Models to Permission Checks

1. `RebacModel` subclasses auto-register through metaclass.
2. Registry config builds type graph from `RebacMeta`.
3. Type graph compiles schema.
4. Published schema defines object types, relations, permissions in SpiceDB.
5. Data mutations produce tuple writes/deletes.
6. Runtime checks query SpiceDB for permission decisions.

If any step is skipped (for example schema not published after model changes), results can be incorrect.

## 3) Sync Behavior by Write Operation

### FK updates

- `save` path tracks old FK values and computes tuple diff.
- Old tuple deleted when relation target changes.
- New tuple written for updated state.

### M2M changes

- `add/remove/clear` hook into `m2m_changed` and sync tuples.

### Through-table role rows

- Create/save/delete can sync tuples when through mapping is configured.
- `bulk_create` sync support requires through model to use `RebacThroughManager`.

### Bulk/low-level writes

- `bulk_create` and `QuerySet.update` need explicit review.
- Some paths may not behave like instance `.save()` with respect to sync assumptions.

## 4) Permission Query Behavior

### Point checks

`can(subject, relation, object)` and `object.has_perm(...)` route through `PermissionEvaluator`.

### Collection checks

`.accessible_by(subject, relation)`:

1. Uses SpiceDB lookup of accessible object IDs.
2. Casts IDs to Django PK type.
3. Ignores malformed IDs with warnings.
4. Applies chunked `pk__in` filters.

### Context and consistency

Use:

- `context`
- `consistency`
- `max_results`

when your app needs deterministic behavior or bounded lookups.

## 5) Tenant and Hierarchy Behavior

1. Tenant-aware flows rely on tenant context and tenant-aware evaluators/managers.
2. Hierarchy permission behavior can depend on optional signal hookup.
3. View-level policy may include `staff_bypass_permissions`; decide this explicitly in app configuration.

## 6) Operational Realities and Caveats

1. Reconcile command is available and useful for drift recovery.
2. Reconcile currently focuses on writing expected tuples from Django state.
3. Full stale remote tuple detection is limited by available adapter read surface.
4. Post-commit sync means write failures can leave temporary drift between DB state and SpiceDB state.

## 7) Symptom-to-Cause Matrix

### Symptom: user denied unexpectedly

Likely causes:

1. User model type not registered.
2. Wrong relation mapping in `RebacMeta`.
3. Schema not republished after model expression changes.
4. Missing tuples due to non-syncing mutation path.
5. Tenant context mismatch.

### Symptom: query returns too many or too few rows

Likely causes:

1. Wrong permission expression.
2. Missing manager (`RebacManager`) on model.
3. Tenant-aware filtering not applied where expected.
4. Staff bypass policy assumptions in hierarchy views.

### Symptom: through-role changes not reflected

Likely causes:

1. Missing `RebacMeta.through` keys or wrong role mapping.
2. Through model missing `RebacThroughManager` for bulk paths.
3. Raw through-table `QuerySet.update` used instead of `.save()`.

### Symptom: behavior differs between local tests and live environment

Likely causes:

1. SpiceDB schema/version mismatch.
2. Different consistency mode assumptions.
3. Drift not reconciled after data migration or bulk ops.
