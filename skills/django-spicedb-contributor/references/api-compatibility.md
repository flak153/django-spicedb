# API Compatibility Policy

Use this policy when changing internals to avoid accidental ecosystem breakage.

## Public Surfaces to Treat as Stable

1. `django_spicedb.__init__` exports (`RebacModel`, `register_type`, `TypeGraph`).
2. `django_spicedb.runtime` exports (`PermissionEvaluator`, `can`).
3. `django_spicedb.sync` exports (`backfill_tuples`, `generate_through_tuples`).
4. Adapter protocol structures in `django_spicedb/adapters/base.py`:
- `TupleKey`
- `TupleWrite`
- `RebacAdapter` method contract
5. Manager/queryset method expectations for app usage:
- `.accessible_by(...)`
- custom bulk behavior hooks where documented by code/tests.

## Compatibility Defaults

1. Preserve method signatures.
2. Preserve parameter meaning.
3. Preserve return shapes/types.
4. Preserve default behavior unless explicitly changing semantics.

## Allowed Internal Refactors

1. Private helper rewrites.
2. Performance improvements preserving externally visible behavior.
3. Logging/observability additions.
4. Validation tightening when backward-compatible with valid inputs.

## Breaking Change Protocol

When breakage is explicitly requested:

1. State break clearly in response.
2. Identify affected APIs/callers.
3. Add migration guidance.
4. Update tests to encode new contract.
5. Update all relevant references in same change set.

## Checklist Before Merge

1. Any exported signature changed?
2. Any behavior changed for existing valid inputs?
3. Any exception type/message changed in externally consumed paths?
4. Any manager/queryset method behavior changed in app-facing flows?
5. Migration note included when needed?
