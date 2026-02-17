# Prompt Pack (Codex + Claude)

Use these prompts as high-signal starters for real implementation work.

## 1) Greenfield Integration

```text
Use $django-spicedb.
Integrate django-spicedb into my Django app from scratch.
I will provide my domain entities and business rules.
Return:
1) model definitions
2) RebacMeta relations/permissions
3) manager choices
4) schema publish and reconcile steps
5) tests I should add first
```

## 2) Rules to Expressions

```text
Use $django-spicedb.
Convert these plain-English authorization rules into precise RebacMeta permission expressions.
Also explain relation prerequisites each expression depends on.
```

## 3) Through Role Membership

```text
Use $django-spicedb.
Implement role-based membership through a join table (member/manager/admin).
Provide complete RebacMeta.through mapping, model managers, and sync-safe mutation guidance.
```

## 4) Existing App Migration

```text
Use $django-spicedb.
I have an existing authorization system and want to migrate incrementally.
Create a phased migration plan with shadow checks, dual-read comparison, cutover criteria, and rollback strategy.
```

## 5) Runtime Integration in Views/Services

```text
Use $django-spicedb.
Show where to place can()/has_perm()/accessible_by() in my existing views/services.
Minimize query overhead and avoid permission check duplication.
```

## 6) Debug Missing Access

```text
Use $django-spicedb.
A user should have permission but is denied.
Give me a deterministic troubleshooting flow with concrete checks for:
type registration, schema state, tuple sync, permission expression, tenant scope.
```

## 7) Debug Over-Permissive Access

```text
Use $django-spicedb.
Users can access resources they should not.
Trace likely over-grant causes in relation mappings and inheritance expressions, and propose precise fixes with tests.
```

## 8) Tenant + Hierarchy Setup

```text
Use $django-spicedb.
Implement tenant-scoped hierarchical permissions in my app.
Include manager/evaluator choices, tenant context handling, and policy notes for staff_bypass_permissions.
```

## 9) Performance and Scale Review

```text
Use $django-spicedb.
Review my integration for performance bottlenecks around permission lookups and queryset filtering.
Recommend optimizations that preserve correctness and testability.
```

## 10) Test Plan Generation

```text
Use $django-spicedb.
Generate a comprehensive test plan for my ReBAC integration:
unit, integration, role transition, inheritance, tenant isolation, and sync edge cases.
```

## 11) Minimal Prompt for Claude Without Skill Loader

```text
Treat source code and tests as the source of truth.
Help implement django-spicedb in my application models using RebacModel/RebacMeta,
sync-aware mutation paths, runtime permission checks, and tenant/hierarchy scoping.
Do not modify django_spicedb internals unless explicitly requested.
```

## 12) Escalate to Contributor Skill

If internal library edits are required, switch prompt context:

```text
Use $django-spicedb-contributor.
```
