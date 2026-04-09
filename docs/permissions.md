# Permission Expressions

Permission expressions are the logic that SpiceDB uses to decide whether a subject can perform an action on an object. They compose relations and other permissions using operators to create rewrite rules.

## Operators

### Union: `+` or `|`
Creates an OR relationship. A subject matches if it has **any one** of the specified relations or permissions.

```
view = owner + viewer
```
Means: A user can view if they are the owner OR they are in the viewer relation.

Both `+` and `|` are equivalent and interchangeable.

### Intersection: `&`
Creates an AND relationship. A subject must match **all** specified relations and permissions.

```
edit = owner & verified
```
Means: A user can edit only if they are the owner AND they have been verified.

### Exclusion: `!`
Negates a relation or permission. A subject matches if they do **not** have the specified relation.

```
public_view = anyone & !banned
```
Means: Anyone can view except those who are banned.

### Grouping: `()`
Controls evaluation order. Without grouping, operators follow standard precedence. Use parentheses to override.

```
access = (owner + viewer) & active
```
Means: Access is granted if (owner OR viewer) AND the account is active.

### Traversal: `->`
Follows a relation to another object and checks a permission on that target object. This enables permission inheritance.

```
view = owner + parent->view
```
Means: A user can view if they are the owner OR if they have view permission on the parent object.

The `->` operator is fundamental to hierarchical permission systems; it allows permissions to flow up or down trees.

## Examples

### Simple Direct Permission
```
view = owner
```
Only the owner can view. Anyone who is the object's owner has view permission.

### Union of Relations
```
view = owner + viewer
```
The owner OR anyone in the viewer relation can view.

### Traversal with Union
```
view = owner + parent->view
```
The owner can view. Also, anyone who can view the parent object can view this object. This is the pattern for hierarchical permissions: if you can view a folder, you can view everything inside it.

### Inheritance with Multiple Levels
```
manage = manager + parent->manage
```
A manager can manage the object. Also, anyone who can manage the parent can manage this object. Permissions propagate recursively up the tree.

### Combining Relations and Traversal
```
view = owner + viewer + parent->view
```
The owner can view. Anyone in the viewer relation can view. Anyone who can view the parent can view this object.

### Intersection Example
```
edit = owner & verified
```
Only the owner can edit, and the owner must also have verified status. Both conditions must be true.

### Complex Expression
```
access = (owner + team->member) & active
```
Access is granted if (owner OR a team member) AND the account is active.

## How It Maps to SpiceDB

Permission expressions compile into SpiceDB's rewrite rules. When you define:

```python
permissions = {
    'view': 'owner + parent->view'
}
```

django-spicedb converts this to SpiceDB's schema DSL:

```
definition document {
    relation owner: user
    relation parent: folder
    permission view = owner + parent->view
}
```

When you call `spicedb.check(document:1, view, user:2)`, SpiceDB evaluates the expression by:
1. Checking if there is a tuple `document:1#owner@user:2`
2. If not, checking if there is a tuple `document:1#parent@folder:X` for some folder X, then recursively checking if `folder:X#view@user:2` is true

SpiceDB handles the recursion and caching; you just write the expression.

## Syntax Rules

- **Token delimiters**: `|`, `&`, `(`, `)`, `!`, `+` are recognized as operators
- **Identifiers**: Relation and permission names are alphanumeric plus underscores
- **Whitespace**: Spaces are ignored
- **Arrow syntax**: `->` is always followed by a relation or permission name with no space required; `parent->view` is valid, `parent -> view` is also valid

## Common Patterns

### Public Access (with Restrictions)
```
read = anyone | role->read
```
Anyone can read, OR anyone who has read on a role object.

### Hierarchical Access
```
permission_name = owner + parent->permission_name
```
This pattern is self-referential: the permission of the same name on the parent flows down. It's used for folders and hierarchical resources.

### Role-Based with Fallback
```
manage = owner + team->manager
```
The owner can always manage. Also, anyone who is a manager on the linked team can manage.

### Restricted Access
```
view = verified_member & !suspended
```
Only verified members can view, and they must not be suspended.

## Read-After-Write Freshness

SpiceDB's default read consistency (`minimize_latency`) serves results from the dispatcher cache, which has a server-side TTL of ~5 seconds. That means a permission check issued immediately after a write can return a stale result — for example, a user who was just granted access via `document.grant(user, "editor")` may get a false `PermissionDenied` on a check that runs in the same request. This causes real bugs in "create-then-redirect" flows.

django-spicedb fixes this automatically by propagating the ZedToken returned from every write through a `ContextVar`. Subsequent reads in the same logical context (thread or async task) will transparently upgrade their consistency to `at_least_as_fresh=<token>`, which guarantees the read sees that write.

### What you get for free

`grant()` and `revoke()` return the ZedToken:

```python
token = document.grant(user, "editor")   # returns a non-empty ZedToken
assert document.has_perm(user, "view")    # True — no explicit consistency needed
```

The sync-registry signal handlers (FK `post_save`, M2M `m2m_changed`, through-table `post_save`, bulk helpers) all record the token they received from SpiceDB inside their `transaction.on_commit()` callback, so the guarantee holds for ORM-driven writes too. The `on_commit` placement is intentional: a rolled-back transaction never poisons the read path with a token for data that doesn't exist.

### WriteTokenMiddleware

`WriteTokenMiddleware` does two jobs:

1. **Scopes** the last-write ZedToken to a single request via `ContextVar`, so a token recorded during one request never leaks into the next.
2. **Persists** the token across requests via `request.session`, so a write in request N (e.g. a form POST that calls `grant()`) is visible to reads in request N+1 (e.g. the redirect target's `can()` check) on the same session. This fixes the common "create-then-redirect" stale-read bug.

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django.contrib.sessions",  # REQUIRED
    # ...
]

MIDDLEWARE = [
    # ...
    "django.contrib.sessions.middleware.SessionMiddleware",
    # WriteTokenMiddleware MUST be listed *below* SessionMiddleware, so
    # that SessionMiddleware saves our modifications to request.session on
    # the way out.
    "django_spicedb.middleware.WriteTokenMiddleware",
    # ...
]
```

It's safe under both WSGI (sync) and ASGI (async), because the underlying `ContextVar` is copied per task, and persistence goes through `request.session` which Django already handles correctly in both modes.

**Requirements**:

- `django.contrib.sessions` must be in `INSTALLED_APPS`. The middleware raises `ImproperlyConfigured` at startup otherwise.
- Must be listed **below** `SessionMiddleware` in `MIDDLEWARE`. If you put it above, session changes happen after `SessionMiddleware` has already saved, and the token silently never persists.

**Session-less backends (DRF + JWT, etc.)**: if you don't use Django sessions, don't install this middleware. Within a single request, `PermissionEvaluator` still reads the contextvar directly, so same-request `grant()` → `can()` flows still work. You only lose cross-request propagation.

**Token lifecycle**: the token lives in the session as an opaque string under the key `_django_spicedb_write_token`. It expires when the session does (logout, cookie max-age). There is no separate TTL — a caught-up replica handles old tokens for free via `at_least_as_fresh`.

**Concurrent writes**: if two requests on the same session both record tokens, the last-finishing one wins. ZedTokens are opaque and can't be compared locally; both witness real writes, so either winner is still correct under `at_least_as_fresh`.

### Opting out of the upgrade

The default `can()` consistency mode is unchanged — it's still `minimize_latency`, so pure reads (no prior write in the context) pay no extra latency. The contextvar **only** kicks in after a same-context write.

If a specific read does not need freshness even after a same-context write, pass `consistency` explicitly:

```python
# Explicit "I don't care about freshness" — forces minimize_latency
can(user, "view", document, consistency="minimize_latency")
```

An explicit `consistency=` argument always wins over the propagated token.

### Low-level API

For callers that want to interact with the contextvar directly:

```python
from django_spicedb.runtime import (
    get_last_write_token,
    record_write_token,
    use_last_write_token,
)

# Inspect the current context's last-write token
token = get_last_write_token()  # '' if none recorded

# Manually record a token (e.g. from a raw adapter call)
record_write_token(token)

# Scope propagation to a with-block
with use_last_write_token():
    # inside here the token starts as '' and is restored on exit
    ...
```
