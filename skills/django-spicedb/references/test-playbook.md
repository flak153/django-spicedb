# Test Playbook

Use this to structure confidence when integrating new permission models.

## 1) Minimal Baseline Suite

Run first:

```bash
pytest -q tests/test_runtime.py tests/test_sync.py tests/test_through_bindings.py
```

This checks:

1. evaluator/queryset permission behavior
2. tuple sync core paths
3. through-binding configuration/sync behavior

## 2) Integration Suite

Run next for end-to-end behavior:

```bash
pytest -q tests/test_group_verification_spicedb.py tests/test_hierarchy_spicedb.py
```

## 3) Scenario Coverage Matrix for App Teams

For each new protected resource, add tests for:

1. direct relation allow
2. direct relation deny
3. inherited allow
4. inherited deny
5. role transition update
6. list filtering via `.accessible_by`
7. tenant boundary deny (if multitenant)

## 4) Sync Mutation Matrix

Exercise each mutation path used by your code:

1. `create/save/delete`
2. FK reassignment
3. M2M add/remove/clear
4. through-table create/save/delete
5. bulk create paths
6. raw update paths

For any raw path, add a test proving your recovery/mitigation strategy.

## 5) Regression Test Rules

When fixing a production incident:

1. Add a failing test that reproduces issue.
2. Patch implementation.
3. Keep regression test.
4. Add adjacent deny test to prevent over-correction.

## 6) Optional Broader Safety Net

If integration touches hierarchy or security-sensitive behavior, also run:

```bash
pytest -q tests/test_hierarchy_integration.py tests/test_security.py
```
