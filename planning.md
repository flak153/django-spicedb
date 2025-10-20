django-spicedb

a general-purpose relationship-based access control library for Django

purpose

django-spicedb gives Django a first-class, idiomatic integration with ReBAC.
it bridges your Django ORM models and views with a SpiceDB (Zanzibar-style) engine, while feeling native to Django developers.

you define relationships, roles, and permission logic declaratively — once — and Django automatically keeps them in sync with SpiceDB and applies them in queries, API views, and templates.

the system focuses on elegance, explicitness, and minimal magic: configuration and runtime behavior are predictable and discoverable, not inferred implicitly.

high-level concepts
1. types

a type represents a class of objects that can participate in authorization decisions. usually it maps 1-to-1 to a Django model (e.g. Org, Workspace, Project, Document).

types have:

a unique name (string key)

optional link to a Django model

a list of relations

a list of permissions

optional parent edges to other types (for hierarchical or delegated access)

optional bindings that tie model fields (FKs, M2Ms) to relations

example mental model:
“a project has relations owner, member, and parent (linking to its workspace). the permission view is granted if you are an owner, member, or if you have view on the parent.”

2. relations

relations are named edges that connect subjects (users, groups, or other objects) to an object.
each relation has a subject type (commonly user or another resource type) and may appear in permission expressions.

3. permissions

permissions are logical expressions (in SpiceDB’s rewrite syntax) composed of relations and other permissions, e.g.:

permission view = member | owner | parent->view
permission edit = owner | parent->edit


the library automatically compiles these into SpiceDB schema statements.

4. parent edges

edges express containment or delegation.
for instance:

workspace.parent = org
project.parent = workspace
document.parent = project


this allows hierarchical inheritance (parent->permission) across arbitrary depth graphs.

5. bindings

bindings tell django-spicedb how to mirror data from Django models into SpiceDB tuples.
they map model fields → relations:

owner = "owner"  (FK to user)
members = "member"  (M2M to user)
parent = "parent"  (FK to workspace)


whenever those fields change, the sync layer emits tuple updates.

6. role templates

roles are convenience bundles of relations and permissions.
you can define them centrally (role_templates.yml or admin ui) and apply them at grant time.

roles are type-scoped (e.g. “workspace_admin” applies to workspace type).

7. grants

a grant assigns a role or relation to a subject on a specific object, optionally with caveats (conditions).
grants are stored in Django and synchronized to SpiceDB.

8. caveats

conditional access rules evaluated at request time.
examples: time windows, feature flags, plan tiers.

design philosophy

declarative, not imperative
developers describe the access graph; the system manages propagation, caching, and enforcement.

layered architecture
separate the policy model (types, relations, permissions) from data sync and runtime evaluation.

opt-in by model
you explicitly register which models participate; nothing hidden or global.

shadow mode first
observe and log decisions before enforcing them in production.

one-line integration
DRF and queryset APIs feel identical to built-ins (has_perm, accessible_by).

composable
supports arbitrary hierarchies; no fixed “organization/region/team” assumptions.

core abstractions
TypeGraph

a registry of all configured types.
responsible for:

validating configuration (no cycles, all parents defined)

compiling to SpiceDB schema DSL

serving type metadata to other layers

TupleSync

watches model changes (signals, m2m updates) and emits tuple writes/deletes.
guarantees idempotence and eventual consistency.
supports optional “outbox” pattern for durability.

RebacAdapter

abstract interface to any ReBAC backend.
SpiceDBAdapter implements it via gRPC:

check(subject, relation, object, context)

lookup_resources(subject, relation, type)

write_tuples([...])

delete_tuples([...])

watch() (for invalidation)

PermissionEvaluator

in-process helper that:

batches checks per request

handles caching and consistency tokens

exposes high-level APIs (can, batch_can, accessible_by)

DRFIntegration

a small permission class:

ReBACPermission


maps HTTP methods to relation names, calls can() behind the scenes, and supports shadow mode logging.

ORMIntegration

a custom manager:

.objects.accessible_by(user, "view")


pushes down SQL filters where possible, else defers to lookup_resources.

AdminConsole

minimal Django admin extension with HTMX:

overview (SpiceDB health, tuple counts)

type graph editor (relations, permissions, parents)

grants list + wizard

access explorer (“who can / why”)

publish & backfill actions

api surface
programmatic checks
can(user, "edit", obj)
batch_can(user, "view", [obj1, obj2, obj3])
lookup_resources(user, "view", Project)

queryset
Project.objects.accessible_by(request.user, "view")

DRF
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["django_rebac.drf.ReBACPermission"]
}

grant / revoke
grant_role(user, "project_editor", project)
revoke_role(user, "project_editor", project)

context / caveats
can(with_context(user, {"now": timezone.now()}), "view", obj)

admin (conceptual)

view all configured types, relations, and permissions

edit policy text

backfill tuples

create grants

run “who can” / “why allowed” queries

internal flow (end-to-end)

policy definition
developer declares types, relations, and permissions in settings or admin.

compile → schema
system generates a SpiceDB schema and pushes it on “publish”.

tuple sync
django signals detect FK/M2M changes and update tuples accordingly.

runtime check
during a request:

DRF or manual code calls can(user, perm, obj)

evaluator checks cache, otherwise calls adapter

decision logged; enforcement depends on shadow/enforce mode

reverse lookup
for list endpoints, .accessible_by() translates to SQL or lookupResources as needed.

observability
metrics and breadcrumbs collected for latency, error, cache hit.

configuration philosophy

configuration can live in:

settings.REBAC (static, code-first)

database tables (editable via admin)

rebac.yml file (optional export/import format)

the config defines the TypeGraph, not runtime behavior.
runtime behavior (e.g. caching, consistency mode, enforce vs shadow) lives in runtime settings.

elegance & ergonomics

symmetry: every check has a reverse (“who can”) query.

clarity: permission rewrites read like natural logic; no magic inference.

predictability: same API everywhere — can, accessible_by, has_perm.

composability: arbitrary parent chains supported by the same syntax (parent->perm).

transparency: generated SpiceDB schema visible and diffable in admin.

progressive disclosure: start with defaults (owner/member/admin) and add complexity only when needed.

scalability considerations

tuple writes batched; idempotent keys prevent duplication.

read caching keyed by (subject, object, relation, epoch).

watch token invalidation ensures freshness.

query depth limited; configurable evaluation budget.

single-node SpiceDB fine for most apps; HA possible later.

extensibility roadmap

alternative adapters (OpenFGA, in-memory)

role templates UI

automatic schema inference

CLI for diff/publish/backfill

audit log explorer

richer caveats (geo, quotas, AB tests)

deliverables summary

django_rebac/ package with clear module boundaries:

types/ (registry, compiler)

adapters/ (spicedb client)

sync/ (signals, outbox)

runtime/ (evaluator, caching)

integrations/ (drf, orm)

admin/ (templates, views)

observe/ (metrics, sentry)

example project demonstrating:

arbitrary hierarchy

DRF endpoints using .accessible_by()

admin console managing grants

documentation: conceptual guide + quickstart

guiding mantra

“describe your relationships once; let Django enforce them everywhere.”

the elegance lies in the fact that developers express access intent declaratively — the same language drives tuples, schema, queryset filtering, and runtime checks — and the whole system feels like part of Django itself.

implementation addendum (touchpoints, precedence, runtime, testing, observability)

1) django touchpoints (what integrates where)

1.1 models that power tuplesync

ReBAC model config store

holds the type graph definition: type name ↔ django model path, relations, permission rewrites, parent edges, field bindings.

persisted so admin can edit, publish, and backfill without redeploys.

grants store

rows representing “subject has role/relation on object,” with optional caveat name/params and expiry.

primary source for ad-hoc access beyond field bindings (e.g., “make alex a project editor”).

jobs/audit

job rows for backfill/publish with status, counts, timestamps.

audit rows for grant changes and publish actions (actor, when, payload snapshot).

contract: only these three internal tables are needed for v1.0. domain models stay unchanged; we bind to their fks/m2ms through configuration.

1.2 signals observed by tuplesync

post_save / post_delete on any registered model

derive tuples from configured bindings (owner fk → relation, parent fk → parent, m2m to users/groups → member/editor).

emit upserts/deletes to spicedb for the changed object only.

m2m_changed on bound manytomany fields

insert/delete tuples for added/removed links.

optional outbox hook

on domain write, a lightweight “outbox” row is created inside the same db transaction; a background worker drains outbox → spicedb. guarantees durability and idempotence under load.

1.3 management commands (no cli scaffolding beyond these)

publish schema

compiles current type graph into spicedb dsl and applies; stores the resulting schema hash/version.

refuses to publish if validation fails or consistency checks trip (e.g., orphaned parent edges).

backfill tuples

scans one or more configured types, derives tuples from bindings and grants, and upserts in batches.

records progress to resume safely after failures.

(optional) repair drift

compares expected tuples (from orm + grants) with spicedb listing; upserts/deletes to converge.

1.4 middleware / request hooks → permissionevaluator

request-scoped evaluator

a small request hook instantiates a per-request evaluator with: subject (user), cache map, latest zedtoken (if writes occurred earlier in the request).

all can()/batch_can()/accessible_by() calls in that request share batching and memoization.

consistency token handoff

when tuple writes happen during the request (e.g., creating an object assigns ownership), the adapter returns its zedtoken. the middleware stores it into the evaluator so subsequent reads use “at least as fresh” consistency.

2) configuration precedence & migration tooling

2.1 sources and precedence

settings (static, code-first)

baseline type graph, adapter endpoint/token, defaults (method→relation map, limits).

highest authority for shape of the system; cannot be mutated at runtime unless explicitly allowed.

database (admin-editable)

mutable layer for type graph details (relations, permission rewrites, parent edges, field bindings) and role templates/grants.

takes precedence over settings for the same keys if the feature flag “db_overrides” is on.

yaml (export/import)

text snapshot of db config for review in prs.

can be applied to db; never overrides settings-only fields.

precedence rule:

for adapter/runtime controls (endpoint, token, timeout, cache ttl, method map): settings only.

for policy (type graph): db if db_overrides=true; else settings.

for role templates: db; yaml import updates db.

grants always live in db.

2.2 preventing divergence across environments

schema hash

every publish stores a normalized schema string and its hash.

on startup and before publish, compute hash from the active source (settings+db) and compare to spicedb’s current schema; warn or block if mismatched.

export on publish

after a successful publish, write a yaml snapshot to disk (and optionally s3) with the schema hash in the filename. this becomes the artifact for ci promotion.

strict/lenient modes

strict: only yaml artifacts signed by ci can be applied in prod; db edits blocked.

lenient (default for mvp): db edits allowed; yaml is advisory.

2.3 diff/apply workflow

diff types

policy diff: compare type graph (relations, rewrites, parents, bindings) vs. last published.

schema diff: human-readable dsl changes.

tuple impact estimate: count changes per relation/type with sampled examples.

apply/publish

validation → schema compile → publish → tuple backfill job (optional, checkbox) → schema hash recorded.

3) runtime details (behaviors and failure modes)

3.1 spicedb grpc calls: retry/backoff

retry strategy

exponential backoff with jitter on unavailable, deadline_exceeded, aborted.

max attempts and deadline configurable; separate policies for read (check, lookup) vs write (write, delete).

circuit breaker

trip on consecutive failures within a sliding window. while open:

in shadow mode: continue logging, never block.

in enforce mode: per-endpoint policy: fail-open or fail-closed.

3.2 error surfaces

developer errors (misconfig, invalid rewrite, missing binding)

raise clear exceptions at publish time; refuse to publish invalid schema.

at runtime, log a deny with reason “policy_misconfig” and surface 500 only if enforcement would cause silent privilege escalation.

engine errors (transport, permission denied to spicedb)

log as “engine_error”; in shadow mode, include diagnostic detail; in enforce, return 403 with generic message if fail-closed, else allow if fail-open.

3.3 shadow-mode logging destinations

decision log

per check: timestamp, subject id, type, object id, relation/permission, decision (allow/deny), consistency, latency, cache_hit, reason (if deny), sample flag.

sink options: stdout json lines, file, or pluggable logger; sampling rate configurable.

roll-up

per request summary: total checks, batched % (number of distinct engine calls / checks), p95 latency.

3.4 caching & invalidation

request-local memoization

exact (subject, type, object, relation, epoch) → decision cached for the request lifetime.

process lru

small lru keyed by (subject_id, type, object_id, relation, epoch). ttl default ~10s; size cap.

epoch is a monotonic integer bumped on watch events (see below).

watch-token invalidation (preferred)

subscribe to spicedb watch; advance a process-wide epoch whenever a tuple touching a known type changes. cache keys with old epoch automatically become cold.

if watch is unavailable, rely on ttl only.

lookup cache (optional)

cache lookupresources results for (subject, type, relation, epoch) with a short ttl; split by page key.

3.5 .accessible_by() planning (pushdown vs lookup)

stage 1: static pushdown

if the permission rewrite simplifies to a direct fk equality (e.g., owner) or tenant fk subset (parent->… collapses to org_id in {...}), emit sql predicates.

use bindings metadata to know fk names; use a precomputed “subjects’ tenant memberships” temp set for the request (e.g., orgs a user admins).

stage 2: hybrid pushdown

if partial pushdowns exist (e.g., “owner or member”), apply the pushdown for each and union results before calling the engine for the remainder.

stage 3: lookup fallback

call lookupresources in pages; collect ids; apply id__in batched.

prefer lookup when rewrites include traversal (parent->perm) or unions over many relations.

tuning knobs

max id__in size, min selectivity before switching to lookup, cap on lookup pages per request.

optional hint parameter to force lookup or force pushdown.

4) testing & local-dev plan

4.1 fixtures and environments

spicedb test container

compose file used in ci and locally; runs single-node spicedb with postgres datastore.

test suite boots it once; tests mark which need the engine (integration) vs. fast unit tests.

fake adapter (unit tests)

in-memory evaluator implementing a limited subset: relations, unions, single-step parent traversal (no cycles).

used for unit tests where the engine is irrelevant (e.g., drf mapping, orm planner choices, parser validation).

4.2 contract tests (schema generation)

golden files

given a type graph input (settings/db), compile schema and compare to a normalized dsl snapshot.

catch regressions in compiler output across versions.

round-trip tests

export db → yaml → import → compile; assert schema hash unchanged.

4.3 tuplesync qa

mutation table

for each binding kind (fk owner, fk parent, m2m member), generate model instances, mutate fields, assert corresponding tuples appear/disappear.

include delete cascades.

idempotence & retries

re-emit the same write batch; assert spicedb state unchanged.

inject transient failures; assert retry policy converges.

4.4 permission semantics parity

scenario matrices

permissions across small hierarchies (2–3 depths) with roles at different levels; assert can() parity against expected truth tables.

4.5 local developer experience

make/readme targets

“start stack,” “publish schema,” “backfill tuples,” “open admin.”

seed data script creating a small hierarchy so explorer works on day one.

5) observability deliverables (make “observe” concrete)

5.1 metrics (prometheus names and labels)

counters

rebac_check_total{relation,type,decision,cache,adapter}

rebac_tuple_write_total{op,source}

rebac_lookup_total{relation,type}

histograms

rebac_check_latency_ms{relation,type,cache}

rebac_lookup_latency_ms{relation,type}

gauges

rebac_cache_entries{kind} (decision, lookup)

rebac_watch_epoch (monotonic integer)

slos (recommended):

p95 rebac_check_latency_ms < 20ms

cache hit rate > 70% on hot endpoints

engine error rate < 0.1%

5.2 logs (structured json lines)

decision log (sampled)

keys: ts, subject_id, type, object_id, relation, decision, latency_ms, cache_hit, consistency, epoch, source (drf, manual, orm), deny_reason (no_path, engine_error, policy_misconfig).

pii policy: ids hashed or truncated by default; opt-in to full ids in dev.

request summary

checks, engine_calls, batch_ratio, max_latency_ms, lookup_pages, policy_version, schema_hash.

5.3 tracing (sentry or datadog apm spans)

spans: rebac.check, rebac.lookup, rebac.tuple_write

span tags: relation, type, cache, consistency, attempts, result

error spans on retries exhausted; link to last engine status.

5.4 troubleshooting workflows

symptom: unexpected deny

use explorer “why” to see missing edges.

check decision log for deny_reason.

if policy_misconfig: run schema diff; validate rewrites.

if no_path: verify grants/bindings and that parent edges exist; run backfill for the type.

symptom: slow list endpoint

review request summary batch ratio and lookup pages.

if pages high: add pushdown hints (owner/org fk) or adjust planner thresholds.

verify cache hit rate; if low, enable watch invalidation; increase ttl cautiously.

symptom: cache staleness

confirm watch epoch increments on tuple writes.

if not, check watch subscription health and spicedb permissions for watch.

temporarily shorten ttl; schedule backfill as sanity check.

6) acceptance checklist (v1.0 “done” gates)

touchpoints wired: signals fire; evaluator has request scope + token handoff.

publish/backfill succeed on a sample multi-level config; schema hash recorded.

.accessible_by() demonstrates pushdown and lookup fallback on real data.

retry/backoff/circuit breaker verified via fault injection.

shadow mode logs present, sampled, and readable.

metrics exported and charted (dash json included).

contract tests stable; tuple sync qa passes; parity scenarios green.

troubleshooting docs included in readme “operate” section.

final note

this addendum intentionally nails “how” without prescribing specific function names or code. it defines where in django the library plugs in, what the runtime guarantees are, and how teams operate, test, and observe it. taken together with the main spec, an llm/engineer can implement a robust, minimal, production-ready v1.0.

documentation home

for v1.0, all operator and developer guides live in the project README. a future dedicated docs site will expand on these foundations.

v1.1 goals (spicedb-first)

deeper spicedb feature coverage (caveats, proofs/explain, consistency knobs, watches).

faster list pages (smarter pushdown + better lookupresources usage).

admin power tools for real ops (grants at scale, diffs, sandbox).

production hardening (cache invalidation across workers, slos, resiliency).

dx polish (policy-as-code, fixtures, docs).

what ships in 1.1

A) caveats & context (first-class)

caveat library (time window, feature plan, ip cidr) with param schemas and validation.

grant-time caveats (ui + python): attach caveats to role/rel grants.

context plumbing: with_context(subject, {"now": ..., "ip": ..., "plan": ...}) flows through drf & templates.

admin “simulate context” in explorer to debug time/plan issues.

acceptance: caveat decisions deterministically match cel semantics; context keys are validated and logged.

B) consistency & zedtokens (easy + safe)

request-local zedtoken handoff: writes during a request return a token; subsequent reads use at_least_as_fresh(zedtoken).

consistency modes exposed in api/drf attribute: fully_consistent, minimize_latency, at_least_as_fresh.

acceptance: race tests (create → check) show no stale denies at the selected mode.

C) watch-driven cache invalidation (multi-process)

subscribe to spicedb watch; on tuple updates, bump a process-wide epoch.

cross-worker fanout via redis pub/sub (or django cache backend) so gunicorn/uvicorn workers invalidate together.

acceptance: cache staleness tests prove sub-second convergence after writes.

D) proofs / “why allowed?” (explain)

explain api wrapper that returns a compact proof (first successful path; include caveat evaluation).

admin explorer shows textual step-by-step (“user→team#member→project#parent→…”) with copyable output.

acceptance: proofs line up with checks; deny flows show first missing edge.

E) query planning 2.0 (faster lists)

static rewrite analysis: detect when view collapses to owner or membership or tenant_admin and push each to sql; only the residual goes to engine.

membership pre-expansion: per-request memo of a user’s direct groups/tenants to power sql filters.

adaptive strategy: switch to lookupresources when sql selectivity is poor (thresholds configurable).

acceptance: p95 list latency improves ≥30% vs 1.0 on mixed datasets; planner decision logged.

F) grants at scale

subtree grants: grant a role at any node (e.g., region) with automatic propagation (no tuple explosion; rely on parent traversals).

bulk operations: csv/yaml import with dry-run and impact preview; stream writes with backpressure & retries.

expiry: time-boxed grants with periodic reaper job.

acceptance: 100k-row grant imports complete within sla; re-runs are idempotent.

G) schema & tuple lifecycle safety

sandbox publish: push schema to a preview store first, run synthetic checks on sampled data, then promote.

tuple diff: estimate tuple churn and show top relation deltas before backfill.

guard rails: prevent publish if it would orphan required relations or exceed configured evaluation depth.

acceptance: operators can predict tuple impact and rollback safely.

H) observability & sre

prom metrics fleshed out (check/lookup latency histograms, deny/allow ratios, cache hit % by endpoint, watch lag).

sentry spans for rebac.check, rebac.lookup, rebac.tuple_write with tags: relation, type, cache, consistency.

runbooks in docs: slow lists, stale cache, unexpected denies; copy-paste promql and log filters.

acceptance: default grafana dashboard & sentry views light up without custom wiring.

I) policy-as-code (optional but powerful)

export/import: one yaml that represents the type graph (types, relations, permissions, parents, bindings) + role templates.

schema hash recorded after publish; ci can block drift across envs.

acceptance: round-trip (db→yaml→db) yields identical schema hash.

J) testing & qa upgrades

contract tests for compiler output (golden dsl per config).

fault-injection tests for adapter retry/backoff & circuit breaker.

tuplesync matrix: fk/m2m create/update/delete → expected tuple changes (idempotent).

acceptance: ci spins spicedb and passes scenario suites for arbitrary hierarchies.

api/ux changes in 1.1 (backward-compatible)

can(subject, relation, obj, *, context=None, consistency=None)

consistency is new (defaults to 1.0 behavior).

model.objects.accessible_by(user, "view", *, prefer=None)

prefer hint: "sql" | "lookup" | None (planner still adaptive).

explain(subject, relation, obj, *, context=None)

returns a structured proof object (rendered as readable text in admin).

grant_role(subject, role_template, obj, *, caveat=None, expires_at=None)

subtree roles supported via parent traversals; no api change required.

admin gains:

caveats tab (define & attach), explain pane in explorer, bulk grants dialog, schema sandbox switch.

non-goals for 1.1 (keep focus)

no openfga adapter.

no visual graph canvas (text proofs only).

no fine-grained per-relation rate limiting or abac attributes outside caveats.

no ha spicedb orchestration (we assume single instance or your infra handles ha).

milestones (suggested)

consistency + watch epoch (B, C)

explain + explorer (D)

planner 2.0 (E)

caveats end-to-end (A)

bulk & subtree grants (F)

schema sandbox + tuple diff (G)

obs + sre docs (H)

policy-as-code (I) + test hardening (J)

versioning stance

1.0 = robust core (spicedb-only, type graph, drf/orm, tuple sync, publish/backfill, basic observability).

1.1 = deeper spicedb features (caveats, explain/proofs, zedtokens, planner 2.0, bulk grants, policy-as-code).

1.2 = ha hardening on the django side (retries/circuit breaker, request-scoped evaluator with token handoff, watch-driven cache epochs + cross-worker invalidation, outage fail-open/closed policies, resumable backfills/outbox).

backward compatibility

all 1.2 features ship off by default with sane fallbacks that preserve 1.0 behavior.

no schema or db migrations required beyond adding optional tables/columns (e.g., an outbox table, a tiny “epoch cache” model). these are additive and non-breaking.

flags & defaults (1.0 apps behave the same)

REBAC.ADAPTER: new keys (pool_size, timeouts, retries, breaker_*). default: minimal retries, breaker disabled.

REBAC.CONSISTENCY.default: still minimize_latency; token handoff used only when present.

REBAC.CACHE: enable_watch=false by default; decision ttl unchanged; no redis required unless watch fan-out is on.

REBAC.DRF.default_fail_policy: inherits 1.0 behavior (deny on engine error for mutating, allow for reads only if you had that set). defaults remain unchanged unless you opt in.

REBAC.BACKFILL: outbox/parallelism optional; default 1.0 single-path stays.

upgrade checklist (1.0 → 1.2)

1. bump package; run migrations (adds optional outbox + jobs fields).

2. do nothing else → behavior matches 1.0.

3. opt in, stepwise:

turn on request-scoped evaluator (safe).

enable zedtoken handoff (safe; improves correctness after writes).

point to redis (or your cache backend) and set enable_watch=true to get epoch invalidation.

configure retries + circuit breaker; set drf fail policy per endpoint.

for heavy writes, enable outbox + resumable backfill.

compatibility notes / risk

multiple workers: if you enable watch epochs without redis fan-out, each worker still invalidates on its own — no worse than 1.0 ttl behavior.

circuit breaker: only affects behavior if you opt in and set a fail policy. defaults keep pre-1.2 semantics.

planner hints: remain purely advisory; disabling them falls back to existing lookup behavior.

deprecations

none. no api removals in 1.2. we may introduce optional params (e.g., prefer on .accessible_by(), consistency on can()), but keep 1.0 call sites working.

rollout plan (recommended)

stage 1: enable request-scoped evaluator + token handoff in a canary env.

stage 2: enable watch epochs + redis fan-out; watch cache hit % and stale-read complaints.

stage 3: set drf fail-policies and adapter retries/breaker; run chaos/fault-injection in staging.

stage 4: turn on outbox for writes; switch backfills to resumable jobs.

semver policy (going forward)

minor (1.x): additive features, new settings with safe defaults, non-breaking migrations.

major (2.0): only if we change public apis (e.g., rename settings keys, alter drf defaults) or require incompatible schema.
