# django-spicedb – Planning & TODOs

---

## Multi-Tenant Hierarchy System (Priority)

**Goal**: Support arbitrary hierarchies for SaaS where each customer (company) defines their own org structure via Admin UI, with permission-scoped analytics, employee data, and history views.

### Key Decisions
- **Bring your own tenant model** - configure via `REBAC['tenant_model'] = 'myapp.Company'`
- **Global SpiceDB types** - single `hierarchy_node` definition, tenant isolation via app layer
- **Defined hierarchy levels** - each tenant defines their levels (Region→Branch→Dept) as `HierarchyTypeDefinition`

### How It Relates to Existing Code

| Existing | New | Relationship |
|----------|-----|--------------|
| `Resource` abstract model | `HierarchyNode` | HierarchyNode is similar but adds tenant + type; could potentially extend Resource |
| `TypeDefinition` model | `HierarchyTypeDefinition` | TypeDefinition is global; HierarchyTypeDefinition is per-tenant |
| `Grant` model | `HierarchyNodeRole` | Grant is generic; HierarchyNodeRole is specific to hierarchy nodes |
| `sync/registry.py` signals | New tenant-aware signals | Extend existing signal pattern for HierarchyNode/HierarchyNodeRole |
| `PermissionEvaluator` | `TenantAwarePermissionEvaluator` | Wraps existing evaluator with tenant isolation checks |
| `RebacQuerySet.accessible_by()` | `TenantAwareRebacQuerySet` | Adds automatic tenant filtering before permission check |

### Phase 1: Core Models

**1.1 Add `HierarchyTypeDefinition`** (in `models.py`)
- [x] Model with: tenant (generic FK via ContentType), name, display_name, slug, level, parent_type (self-FK)
- [x] JSON fields for: relations, permissions, UI metadata (icon, color)
- [x] Unique constraint on (tenant, slug)

**1.2 Add `HierarchyNode`** (in `models.py`)
- [x] Model with: tenant (generic FK), hierarchy_type (FK), name, slug, parent (self-FK)
- [x] Denormalized: path (materialized path), depth
- [x] Methods: `get_ancestors()`, `get_descendants()`, `spicedb_object_ref`

**1.3 Add `HierarchyNodeRole`** (in `models.py`)
- [x] Through table: node (FK), user (FK), role (choice field)
- [x] Unique constraint on (node, user, role)
- [x] `inheritable` flag for parent→permission propagation

**1.4 Tenant Configuration** (in `conf.py`)
- [ ] Add `REBAC['tenant_model']` setting (e.g., `'myapp.Company'`)
- [ ] Add `REBAC['tenant_fk_name']` setting (e.g., `'company'`)
- [ ] Helper: `get_tenant_model()` returns the model class
- [ ] Helper: `get_tenant_content_type()` returns ContentType for tenant model

**1.5 Migrations**
- [ ] Create migration for new models
- [ ] Run `makemigrations django_rebac`

**1.6 Admin Registration**
- [ ] Register `HierarchyTypeDefinition` with list display, filters
- [ ] Register `HierarchyNode` with tree view (or at least parent filter)
- [ ] Register `HierarchyNodeRole` as inline on HierarchyNode

### Phase 2: SpiceDB Schema

**2.1 Global Schema for Hierarchies**
```zed
definition hierarchy_node {
    relation parent: hierarchy_node
    relation manager: user
    relation viewer: user
    permission manage = manager + parent->manage
    permission view = viewer + manage + parent->view
}
```

**2.2 Schema Integration**
- [ ] Add `hierarchy_node` type to default `settings.REBAC['types']`
- [ ] Or: auto-register when HierarchyTypeDefinition exists
- [ ] Ensure `publish_rebac_schema` includes hierarchy_node

### Phase 3: Tuple Sync for Hierarchy

**3.1 Signal Handlers** (new file: `django_rebac/hierarchy/signals.py`)
- [ ] `post_save` on `HierarchyNode`: write parent tuple
- [ ] `post_delete` on `HierarchyNode`: delete parent tuple
- [ ] `post_save` on `HierarchyNodeRole`: write role tuple (e.g., `hierarchy_node:123#manager@user:456`)
- [ ] `post_delete` on `HierarchyNodeRole`: delete role tuple

**3.2 Integrate with Existing Registry**
- [ ] Option A: Extend `sync/registry.py` to handle hierarchy models
- [ ] Option B: Separate registry in `hierarchy/` package
- [ ] Register signals in `apps.py` ready hook

### Phase 4: Tenant-Aware Evaluation

**4.1 Tenant Context** (new file: `django_rebac/tenant/context.py`)
- [ ] Thread-local `_current_tenant`
- [ ] `get_current_tenant()` / `set_current_tenant()`
- [ ] Context manager: `with tenant_context(tenant):`

**4.2 Tenant Middleware** (new file: `django_rebac/tenant/middleware.py`)
- [ ] Resolve tenant from: subdomain, header (`X-Tenant-ID`), or user's default
- [ ] Set `request.tenant` and thread-local
- [ ] Clear on response

**4.3 Tenant-Aware Evaluator** (extend `runtime/evaluator.py`)
- [ ] `TenantAwarePermissionEvaluator(subject, tenant=None)`
- [ ] Override `can()`: check `obj.tenant_id == self._tenant.id` BEFORE SpiceDB call
- [ ] Cross-tenant access = automatic deny (security critical)

**4.4 Tenant-Aware QuerySet** (extend `integrations/orm.py`)
- [ ] `TenantAwareRebacQuerySet` with auto tenant filtering
- [ ] `accessible_by()` filters by tenant FIRST, then calls LookupResources

### Phase 5: Optimized Reverse Lookups

**5.1 Hierarchy Lookup Helper** (new file: `django_rebac/hierarchy/lookups.py`)
- [ ] `TenantHierarchyLookup(user, tenant)`
- [ ] `get_accessible_hierarchy_nodes(permission)` - returns Set[int] of node IDs
- [ ] Cache per request (avoid repeated LookupResources calls)

**5.2 Filter by Hierarchy Node**
- [ ] For models with `hierarchy_node` FK: filter `hierarchy_node_id__in=accessible_nodes`
- [ ] More efficient than per-object LookupResources

### Phase 6: Admin UI

- [ ] Hierarchy type builder (define levels for a tenant)
- [ ] Hierarchy node tree view (create/edit/delete nodes)
- [ ] Role assignment inline
- [ ] Permission tester ("What can user X see?")

### Phase 7: Testing

- [ ] Unit tests for HierarchyNode path/depth calculation
- [ ] Unit tests for HierarchyNodeRole tuple generation
- [ ] Integration test: create hierarchy, assign roles, check permissions
- [ ] Integration test: tenant isolation (user A can't see tenant B's nodes)

---

## Schema & Policy Source of Truth

**Approach**: Django model `class Rebac` declarations are the source of truth. SpiceDB schema is generated from models (not the other way around). `FK("owner")` declares both the relation AND the binding.

- [ ] `rebac_compile` command: generate `schema.zed` from model declarations (checked into git for review/audit).
- [ ] Update `publish_rebac_schema` to use compiled schema from models.
- [ ] Store schema hash on publish for drift detection; warn if generated schema differs from published.
- [ ] `rebac_diff` command: preview schema changes before publish.
- [ ] Add `rebac_migrate_config` command to convert existing `settings.REBAC['types']` into model `class Rebac` declarations.
- [ ] Cache compiled TypeGraph with invalidation on model changes.
- [ ] Escape hatch: `REBAC['schema_source'] = "external"` for multi-service setups where schema is owned elsewhere.

## Model-Adjacent Policy Declarations
- [ ] Implement `RebacMixin` with inner `class Rebac` API (type name, relations, permissions, metadata).
- [ ] Binding descriptors that unify relation + sync: `FK(field)`, `M2M(field)`, `Grantable(subject_types...)`.
- [ ] Auto-infer subject types from FK/M2M targets (e.g., `FK("owner")` on User FK → `relation owner: user`).
- [ ] Auto-discover models with `class Rebac` at Django app ready; register with TypeGraph.
- [ ] Validation: FK target must have Rebac declaration, permission expressions reference valid relations.
- [ ] Document pattern and add regression tests for tuple sync + evaluator using inline declarations.

## Grants Model (Ad-Hoc Permissions)
- [ ] `Grant` model: subject (generic FK), relation, object (generic FK), optional expiry, created_by, created_at.
- [ ] Sync grant tuples to SpiceDB alongside binding-derived tuples.
- [ ] `grant(subject, relation, obj)` / `revoke(subject, relation, obj)` helper functions.
- [ ] Admin interface for viewing/creating/revoking grants.
- [ ] Bulk grant import/export (CSV/YAML) for migrations and seeding.

## Tuple Sync Enhancements
- [ ] Refactor registry to use new binding descriptors (avoid settings dependency).
- [ ] Ensure FK lookups use `_id` cache (no DB hits on delete); clarify optional fields handling.
- [ ] Add `GroupMember(field)` binding for Django Group auto-sync (emits `group:X#member` tuples).
- [ ] Improve error reporting when bindings reference missing fields or relations.
- [ ] Expand tests for group membership, delete cascades, and optional parent edges.
- [ ] Batch tuple writes: collect per-request, flush to SpiceDB in single call.

## Adapter & Runtime Polishing
- [ ] Add tests covering `django_rebac.adapters.factory` (configuration, reset).
- [ ] Enhance `PermissionEvaluator` to accept injected adapters, context merging, consistency options.
- [ ] Batch-check API: `batch_can()` using SpiceDB bulk check (single RPC instead of N calls).
- [ ] Watch-token-based cache invalidation (SpiceDB) and TTL fallback.
- [ ] Logging & metrics hooks (structured decisions, cache stats, adapter latency).

## Error Resilience
- [ ] Configurable timeouts for SpiceDB gRPC calls.
- [ ] Retry with exponential backoff for transient failures (UNAVAILABLE, DEADLINE_EXCEEDED).
- [ ] Circuit breaker: trip after N consecutive failures, auto-recover after cooldown.
- [ ] Fail-open vs fail-closed policy, configurable per-endpoint or globally.
- [ ] `REBAC['on_error']`: `"deny"` (fail-closed) / `"allow"` (fail-open) / `"raise"`.

## Shadow Mode
- [ ] `REBAC['mode']`: `"shadow"` (log decisions, never deny) / `"enforce"` (deny on failure).
- [ ] Per-model or per-view override via decorator/mixin attribute.
- [ ] Decision log model: subject, object, relation, result, would_deny, latency_ms, timestamp.
- [ ] Management command to replay shadow logs and compare against current policy.

## SQL Pushdown for `accessible_by()`
- [ ] Detect simple permission expressions: `view = owner` → `filter(owner=user)`.
- [ ] Tenant expansion: pre-load user's org/team memberships, push `org_id__in` filters.
- [ ] Configurable selectivity threshold: fall back to `lookup_resources` when pushdown isn't selective.
- [ ] `prefer="sql"` / `prefer="lookup"` hint parameter on `accessible_by()`.

## Django Integrations
- [ ] Override `has_perm` for object checks via lightweight auth backend (optional install).
- [ ] Decorators/mixins (`@require_relation`, `ReBACRequiredMixin`, template tag) for FBVs/CBVs/templates.
- [ ] DRF defaults: global permission class + per-action overrides; ensure queryset pushdown is automatic.
- [ ] Admin inline to display current grants and why-allowed explanation.
- [ ] Auto-register Django `auth.Permission` codes per relation (content type aware) and map to ReBAC checks.
- [ ] Middleware helper for tenant context extraction (org scoping) with pluggable resolver.

## Admin & UX
- [ ] Minimal admin dashboards: policy list, role templates, grant management, shadow-mode status.
- [ ] “Why allowed?” explorer with path visualization (leveraging SpiceDB explain API).
- [ ] Shadow-mode dashboard (log allow/deny decisions; flip to enforce per endpoint).
- [ ] Role/grant wizard with bulk import/export (CSV/YAML).
- [ ] Policy diff preview (schema/tuple churn) before publish/backfill.

## Observability
- [ ] Emit structured logs for every `can()` (subject, object, relation, decision, cache hit, zedtoken).
- [ ] Metrics: check counters, latency histograms, cache hit rate, tuple sync duration.
- [ ] Optional audit sink (DB table or log handler for tuple/grant changes).
- [ ] Sample Grafana dashboard / Prometheus ruleset for core metrics.

## Testing & Tooling
- [ ] Enhance test suite: integration fixture with model-based TypeGraph, more recording adapter coverage.
- [ ] Dockerized SpiceDB fixture improvements (faster startup, snapshot caching).
- [ ] Fake adapter for pure unit tests (limited semantics: relations, unions, single-step parent traversal).
- [ ] `rebac_lint` command: validate model declarations, check for orphan relations, permission expression errors.
- [ ] `rebac_check <subject> <relation> <object>`: CLI permission check for debugging.
- [ ] Add multi-tenant, group, and caveat scenarios to example project integration tests.

## Documentation
- [ ] Rewrite README with model `class Rebac` declaration examples (replace settings-based config).
- [ ] Update developers.md: migration path from `settings.REBAC`, best practices, caveats.
- [ ] Add recipes (hierarchy, SaaS orgs, doc sharing) with copy/paste model snippets.
- [ ] Provide FAQ: "How do Django Groups map?", "How do caveats/context work?", "How to debug access?"
- [ ] Document multi-tenant setup (middleware, context injection) and adapter configuration.
- [ ] Produce quickstart screencasts / gifs once model declaration API stabilizes.

## Release & Packaging
- [ ] Define support matrix (Django/Python versions) and add CI matrix.
- [ ] Build publishing workflow (wheel + changelog + release notes).
- [ ] Versioned example project demonstrating model declarations, grants, DRF integration.
