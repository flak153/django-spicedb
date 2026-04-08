"""Django middleware that scopes SpiceDB write-token propagation.

Wraps each request in :func:`use_last_write_token` so that a ZedToken
recorded during one request never leaks into the next. Safe under both
WSGI (sync) and ASGI (async), because the contextvar backing the token is
copied per-task.
"""

from __future__ import annotations

from asgiref.sync import iscoroutinefunction, markcoroutinefunction

from django_spicedb.runtime.last_write_token import use_last_write_token


class WriteTokenMiddleware:
    """Scope ZedToken propagation to a single request/response cycle."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._is_async = iscoroutinefunction(get_response)
        if self._is_async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self._is_async:
            return self._acall(request)
        with use_last_write_token():
            return self.get_response(request)

    async def _acall(self, request):
        with use_last_write_token():
            return await self.get_response(request)
