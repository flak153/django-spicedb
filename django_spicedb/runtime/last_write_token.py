"""Context-local propagation of the most recent SpiceDB write ZedToken.

SpiceDB's default ``minimize_latency`` read consistency hits the dispatcher
cache, which has a server-side TTL of ~5 seconds. A read that follows a write
in the same request can therefore return a stale result, causing false
``PermissionDenied`` errors on flows like create-then-redirect.

The fix is to tell SpiceDB "be at least as fresh as this ZedToken" on the
read. The token is returned by every write RPC, and this module stores the
most recent one in a :class:`contextvars.ContextVar` so reads performed later
in the same logical context (thread, async task, or request) can automatically
upgrade their consistency without the caller threading the token through by
hand.

``ContextVar`` (not ``threading.local``) is required: it is the only primitive
that isolates state correctly across both OS threads and ``async def`` tasks.
Thread-locals leak across ``await`` boundaries.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Iterator

_last_write_token: ContextVar[str] = ContextVar(
    "django_spicedb_last_write_token", default=""
)


def record_write_token(token: str) -> None:
    """Record a ZedToken returned from a successful write.

    Empty strings are treated as no-ops so callers can unconditionally pass
    the return value of ``adapter.write_tuples(...)`` without checking.
    """

    if token:
        _last_write_token.set(token)


def get_last_write_token() -> str:
    """Return the most recent ZedToken for the current context.

    Returns an empty string when no write has been recorded in this context.
    """

    return _last_write_token.get()


@contextlib.contextmanager
def use_last_write_token() -> Iterator[None]:
    """Scope token propagation to a ``with`` block.

    On entry the context's last-write-token is cleared; on exit the previous
    value is restored. The typical caller is :class:`WriteTokenMiddleware`,
    which uses this to ensure a token recorded during one request never leaks
    into the next.
    """

    reset_token = _last_write_token.set("")
    try:
        yield
    finally:
        _last_write_token.reset(reset_token)
