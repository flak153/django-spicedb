# Contributor Prompt Pack

## 1) Internal Bug Fix With Regression Safety

```text
Use $django-spicedb-contributor.
Fix this internal bug in django_spicedb.
Required output:
1) failing test reproduction
2) minimal patch plan by subsystem
3) compatibility impact assessment
4) targeted test commands
5) short migration note if behavior changes
```

## 2) Internal Feature Addition

```text
Use $django-spicedb-contributor.
Implement this internal feature with minimal API breakage.
Map changes across core, type graph, sync/runtime/adapter modules as needed.
Include invariants that must remain true.
```

## 3) Sync Pipeline Refactor

```text
Use $django-spicedb-contributor.
Refactor tuple synchronization behavior.
Trace FK, M2M, through, and queryset-update paths and preserve semantics unless explicitly changed.
Add regression tests for edge cases.
```

## 4) Evaluator Semantics Change

```text
Use $django-spicedb-contributor.
Modify permission evaluator/queryset semantics.
Validate relation/subject parsing, context merge/freeze behavior, cache behavior, and accessible_by effects.
```

## 5) Adapter Boundary Evolution

```text
Use $django-spicedb-contributor.
Change adapter implementation/protocol behavior.
Keep base protocol, spicedb implementation, and factory config in sync.
Call out any compatibility implications immediately.
```

## 6) TypeGraph and Schema Evolution

```text
Use $django-spicedb-contributor.
Extend TypeGraph/schema capability.
Update extraction, validation, schema compilation, and affected sync/runtime behavior.
Require new tests for unknown-parent, relation-subject, expression, and binding validation.
```

## 7) Security-Hardening Pass

```text
Use $django-spicedb-contributor.
Audit and harden internal security-sensitive paths.
Focus on input validation, bypass behavior, sync failure modes, and cache/consistency semantics.
Return findings sorted by severity and patch plan.
```

## 8) Pre-Release Stabilization

```text
Use $django-spicedb-contributor.
Prepare internals for release:
1) run subsystem matrix
2) run cross-cutting suites
3) identify API/behavior changes
4) draft release notes and migration notes
```
