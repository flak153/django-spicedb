# Release Checklist (Contributor)

Use this before finalizing major internal changes.

## 1) Code and Contract Review

1. Verify patch is scoped to intended subsystem.
2. Verify public API compatibility policy was followed.
3. Verify any semantic changes are explicitly documented.

## 2) Test Validation

1. Run touched subsystem tests from `subsystem-test-matrix.md`.
2. Run cross-cutting safety set:

```bash
pytest -q tests/test_runtime.py tests/test_sync.py tests/test_security.py
```

3. Run SpiceDB integration suites when changes touch adapter/sync/runtime behavior.

## 3) Regression Guarantees

1. Ensure bug reproduction test exists for fixed issues.
2. Ensure deny-side regression exists for auth changes (avoid over-grant).
3. Ensure tenant boundary tests exist for tenant-related changes.

## 4) Operational Safety

1. Confirm reconcile command behavior still consistent.
2. Confirm error handling paths keep system observable (logging/errors).
3. Confirm no accidental silent failure paths were introduced.

## 5) Documentation and Skill References

1. Update contributor references if contracts/workflows changed.
2. Update app-facing skill docs when app integration semantics changed.
3. Ensure prompt packs reflect current workflow.

## 6) Final Handoff Summary

Include:

1. What changed.
2. What remained compatible.
3. Known caveats remaining.
4. Recommended follow-up work.
