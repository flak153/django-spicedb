# django-spicedb

Declarative, relationship-based access control for Django, backed by [SpiceDB](https://authzed.com/spicedb). Describe your access graph once; let Django enforce it everywhere.

- Native Django concepts: types map to models, relations bind to fields, permissions reuse familiar APIs like `can()` and `.objects.accessible_by()`.
- SpiceDB-first: schema generation, tuple sync, and runtime checks are first-class, observable, and production-ready.
- Opt-in ergonomics: no magic global state, clear defaults, and progressive disclosure of advanced features (caveats, proofs, caching, HA).

The roadmap and design are captured in [`planning.md`](planning.md). This README reflects the target experience and will track implementation progress as modules land.

---

## Why django-spicedb?
- **Single source of truth** for relationships, roles, and permissions.
- **Idiomatic Django** integrations across ORM managers, DRF view permissions, templates, and admin tooling.
- **Battle-ready** runtime: tuple sync with durability options, caching with watch-driven invalidation, structured observability, and feature gates.
- **Incremental adoption**: start in shadow mode, enforce selectively, scale to high availability without breaking existing apps.

---

## Core concepts
- **Types** – Named resources (often Django models) that own relations and permissions. Enable parent chains for hierarchical access.
- **Relations** – Named edges from an object to subjects (`user`, `team`, another type). Fuel permission rewrites and tuple syncing.
- **Permissions** – SpiceDB rewrite expressions that compose relations/other permissions (`view = owner | member | parent->view`).
- **Bindings** – Declarative links between model fields (FK, M2M) and relations; drive automatic tuple sync on saves/m2m changes.
- **Grants & Roles** – Store ad-hoc assignments (user X is project editor). Roles bundle relations/permissions; grants may carry caveats.
- **Caveats & Context** – Conditional access evaluated at check time (plan tiers, geography, time windows) with CEL semantics.
- **TupleSync** – Signals, outbox, and backfill jobs that keep SpiceDB tuples in lockstep with Django.
- **PermissionEvaluator** – Request-scoped helper that batches checks, respects zedtokens, and powers `.accessible_by()`.
- **Admin Explorer** – Inspect policy, grants, and “why allowed” proofs; run publish/backfill/repair jobs; manage caveats and bulk grants.

---

## Package layout
- `django_rebac/types/` – TypeGraph registry, validation, schema compiler.
- `django_rebac/adapters/` – SpiceDB adapter (gRPC, retries, circuit breaker) plus abstract interface for alternate backends.
- `django_rebac/sync/` – TupleSync orchestrator, outbox worker, jobs/audit models.
- `django_rebac/runtime/` – PermissionEvaluator, caching, context handling, explain/proof generation.
- `django_rebac/integrations/` – ORM manager, DRF permission class, template tags.
- `django_rebac/admin/` – Admin dashboard, Explorer, bulk grant tooling.
- `django_rebac/observe/` – Metrics, structured logs, tracing helpers.
- `django_rebac/management/commands/` – `publish_rebac_schema`, `rebac_backfill`, `rebac_repair`.
- `example_project/` – Full Django project illustrating integration end-to-end.
- `tests/` – Unit and integration suites (SpiceDB container fixture, fake adapter).

---

## Version roadmap
- **v1.0 – Robust core**  
  TypeGraph + config store, tuple sync, publish/backfill workflow, request-scoped evaluator, ORM/DRF integrations, grants, admin explorer, baseline metrics/logs.
- **v1.1 – SpiceDB-first depth**  
  Caveats/context pipeline, proofs/explain, zedtoken consistency controls, query planner 2.0, bulk/subtree grants, policy-as-code workflow, expanded observability.
- **v1.2 – HA hardening**  
  Advanced retry/breaker knobs, watch-driven cross-worker cache invalidation, outage fail-open/closed policies, resumable backfills/outbox, Redis fan-out, opt-in feature gates.

SemVer policy: 1.x releases are additive with safe defaults and non-breaking migrations; 2.0 reserved for API or schema breaking changes.

---

## Quickstart (target v1.0 experience)
> **Assumptions**: Python 3.11, Docker, and `poetry` are installed. Commands run from repo root.

1. **Install dependencies**
   ```bash
   poetry install
   ```
2. **Start SpiceDB + Postgres**
   ```bash
   docker compose up spicedb
   ```
3. **Bootstrap Django database**
   ```bash
   poetry run python manage.py migrate
   poetry run python manage.py createsuperuser
   ```
4. **Publish REBAC schema** (compiles current TypeGraph and applies to SpiceDB)
   ```bash
   poetry run python manage.py publish_rebac_schema
   ```
5. **Backfill tuples** (syncs bindings + grants into SpiceDB)
   ```bash
   poetry run python manage.py rebac_backfill
   ```
6. **Run the example project**
   ```bash
   poetry run python manage.py runserver
   ```
7. **Explore the admin UI**  
   Visit `http://localhost:8000/admin/` to inspect types, grants, and run Explorer (“who can”, “why allowed”).

Shadow mode is the default: decisions are logged but not enforced until toggled in settings or admin.

---

## Local development guide
- **Run tests** (requires Docker; the suite will start SpiceDB via `docker compose` and skips integration cases if the daemon is unavailable)
  ```bash
  poetry run pytest
  ```
- **Lint / type check** (planned additions)  
  ```bash
  poetry run ruff check
  poetry run mypy django_rebac
  ```
- **Seed demo data**
  ```bash
  poetry run python manage.py rebac_seed_demo
  ```

---

## Configuration overview
- `settings.REBAC`: core switchboard (adapter endpoint/token, defaults, feature flags).
- **Precedence**: settings → DB overrides → YAML import/export (policy-as-code). Schema hash recorded on publish.
- **Feature toggles**: shadow vs enforce mode, cache TTLs, watch invalidation, circuit breaker policies, outbox enablement.
- **Admin workflows**: policy diff, sandbox publish, tuple impact estimation, grant audit trail.

See [`planning.md`](planning.md) for full precedence rules, feature flags, and HA guidance.

---

## Observability (v1.0+)
- **Metrics**: `rebac_check_total`, `rebac_tuple_write_total`, latency histograms, cache gauges.
- **Logs**: structured decision logs (with deny reasons), request summaries.
- **Tracing**: spans for `rebac.check`, `rebac.lookup`, `rebac.tuple_write`.
- **Runbooks**: troubleshoot slow listings, stale caches, unexpected denies via README “Operate” section.

---

## Contributing
- Open issues/PRs referencing the relevant section of `planning.md`.
- Include unit tests for new modules and integration tests when touching SpiceDB interactions.
- Update this README’s status/quickstart as features ship.

---

## Current status snapshot

### Core Features (Complete)
- ✅ **TypeGraph** with validation, schema compilation, and SpiceDB DSL generation
- ✅ **Model-centric configuration** via `RebacMeta` inner class (like Django's `Meta`)
- ✅ **Auto-inferred bindings** from FK/M2M field types
- ✅ **TupleSync** with `post_save`, `post_delete`, `m2m_changed` signal handlers
- ✅ **FK change tracking** via `pre_save` to delete stale tuples on relationship changes
- ✅ **Transaction safety** with `transaction.on_commit()` for all SpiceDB writes
- ✅ **PermissionEvaluator** + `can()` convenience function
- ✅ **RebacManager** with `.accessible_by(user, permission)` queryset filtering
- ✅ **Group-based access control** pattern with role-based membership (member/manager)
- ✅ **Permission inheritance** via `parent->permission` expressions
- ✅ **SpiceDB adapter** with gRPC, `lookup_resources`, `lookup_subjects`, consistency controls
- ✅ **Management commands**: `publish_rebac_schema`, `rebac_backfill`

### Infrastructure (Complete)
- ✅ `docker-compose.yaml` for SpiceDB + Postgres
- ✅ 196 tests with SpiceDB integration coverage (auto-starts via Docker Compose)
- ✅ Recording adapter for unit testing without SpiceDB
- ✅ Comprehensive FK change tracking with `subject_field`/`object_field` support (tested)

### In Progress
- 🔜 Admin explorer UI for policy inspection
- 🔜 DRF permission class integration
- 🔜 Caveats/context pipeline
- 🔜 Observability stack (metrics, structured logs, tracing)
- 🔜 Watch-driven cache invalidation

This project is actively evolving—follow the roadmap and feel free to contribute!
