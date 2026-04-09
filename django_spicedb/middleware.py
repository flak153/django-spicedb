"""Django middleware that scopes and persists SpiceDB write-token propagation.

Scopes the last-write ZedToken to a single request via
:func:`use_last_write_token` *and* persists it across requests via the user's
session, so a write in request N is visible to reads in request N+1 on the
same session. Safe under both WSGI (sync) and ASGI (async), because the
contextvar backing the token is copied per-task.

Requirements:

* ``django.contrib.sessions`` must be in ``INSTALLED_APPS``.
* This middleware must be listed **below** ``SessionMiddleware`` in
  ``MIDDLEWARE``, so that ``SessionMiddleware`` saves any modifications this
  middleware makes to ``request.session`` on the way out.
"""

from __future__ import annotations

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from django_spicedb.runtime.last_write_token import (
    get_last_write_token,
    record_write_token,
    use_last_write_token,
)

SESSION_TOKEN_KEY = "_django_spicedb_write_token"


class WriteTokenMiddleware:
    """Scope and persist SpiceDB ZedToken propagation.

    Rehydrates the last-write token from ``request.session`` on the way in
    and persists the post-view token back into the session on the way out.
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        if "django.contrib.sessions" not in settings.INSTALLED_APPS:
            raise ImproperlyConfigured(
                "django_spicedb.middleware.WriteTokenMiddleware requires "
                "'django.contrib.sessions' in INSTALLED_APPS. Either add "
                "sessions or remove this middleware."
            )
        self.get_response = get_response
        self._is_async = iscoroutinefunction(get_response)
        if self._is_async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self._is_async:
            return self._acall(request)
        with use_last_write_token():
            self._rehydrate(request)
            response = self.get_response(request)
            self._persist(request)
            return response

    async def _acall(self, request):
        with use_last_write_token():
            self._rehydrate(request)
            response = await self.get_response(request)
            self._persist(request)
            return response

    @staticmethod
    def _rehydrate(request) -> None:
        token = request.session.get(SESSION_TOKEN_KEY, "")
        if token:
            record_write_token(token)

    @staticmethod
    def _persist(request) -> None:
        token = get_last_write_token()
        if not token:
            return
        # Last-writer-wins on concurrent same-session requests: ZedTokens are
        # opaque, can't be compared locally, and both witness real writes so
        # either winner is still correct. Don't try to be clever with max().
        if request.session.get(SESSION_TOKEN_KEY) != token:
            request.session[SESSION_TOKEN_KEY] = token
