# Changelog

## 0.5.0

### Breaking

- **`WriteTokenMiddleware` now requires `django.contrib.sessions`** in `INSTALLED_APPS`. The middleware raises `ImproperlyConfigured` at startup if sessions are not installed. If your deployment is a pure-API backend (DRF + JWT, no Django sessions), remove `django_spicedb.middleware.WriteTokenMiddleware` from `MIDDLEWARE` — within a single request, `PermissionEvaluator` still reads the contextvar directly, so same-request `grant()` → `can()` flows still work.
- **`WriteTokenMiddleware` must be listed below `SessionMiddleware`** in `MIDDLEWARE`. `SessionMiddleware` saves modifications to `request.session` on the way out, so any middleware that writes to the session must run more innermost. Listing it above silently results in no cross-request persistence.

### New

- **Cross-request ZedToken propagation via session.** `WriteTokenMiddleware` now persists the last-write ZedToken in `request.session` under the key `_django_spicedb_write_token`. On the next request in the same session the token is rehydrated into the contextvar and `PermissionEvaluator` automatically upgrades consistency to `at_least_as_fresh(<token>)`. This fixes the common "form POST calls `grant()` → redirect → next request's `can()` returns stale False" race against SpiceDB's ~5s dispatcher cache and replica lag.
- Token lives as long as the session does (logout, cookie max-age). No separate TTL setting — a caught-up replica handles old tokens for free under `at_least_as_fresh`.

### Migration

- **Standard Django apps** already using `django.contrib.sessions`: no changes required beyond bumping the package. Verify that `WriteTokenMiddleware` is listed below `SessionMiddleware` in `MIDDLEWARE`.
- **DRF + JWT backends** without sessions: remove `django_spicedb.middleware.WriteTokenMiddleware` from `MIDDLEWARE`. You keep same-request protection via the contextvar.

## 0.4.0

- Auto-propagate SpiceDB write ZedTokens for read-after-write freshness. `RebacModel.grant()` / `revoke()` and the sync registry now record tokens into a `ContextVar` after writes; `PermissionEvaluator.can()` / `batch_check()` / `lookup_resources()` auto-upgrade consistency to `at_least_as_fresh(<token>)` when no explicit `consistency=` is supplied and a prior write exists in the current context.
- Adapter Protocol: `write_tuples()` and `delete_tuples()` now return `str` (the ZedToken, or `""` for no-op writes). BC break vs 0.3.x.
- New `WriteTokenMiddleware` scopes propagation per-request under both WSGI and ASGI.
