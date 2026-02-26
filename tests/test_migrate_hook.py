"""Tests for the post_migrate sync hook."""

from __future__ import annotations

import logging
from unittest.mock import patch, MagicMock

import pytest
from django.db.models.signals import post_migrate

from django_spicedb.sync.migrate_hook import (
    handle_post_migrate,
    reset_migrate_hook,
)


@pytest.fixture(autouse=True)
def _reset_hook():
    """Ensure the once-per-migrate guard is cleared between tests."""
    reset_migrate_hook()
    yield
    reset_migrate_hook()


def _handler_is_connected():
    """Check if handle_post_migrate is among post_migrate receivers."""
    for receiver_tuple in post_migrate.receivers:
        # Django stores receivers as (lookup_key, weakref_to_callable)
        receiver = receiver_tuple[1]
        # Could be a weakref or a strong ref
        resolved = receiver() if callable(getattr(receiver, "__call__", None)) and hasattr(receiver, "__self__") else receiver
        if callable(resolved) and resolved is handle_post_migrate:
            return True
        # weakref case
        if hasattr(receiver, "__func__"):
            continue
        try:
            deref = receiver()
        except TypeError:
            deref = receiver
        if deref is handle_post_migrate:
            return True
    return False


# -------------------------------------------------------------------
# 1. Signal connection respects sync_on_migrate setting
# -------------------------------------------------------------------


class TestSignalConnection:
    """post_migrate handler is connected by default (opt-out via sync_on_migrate=False)."""

    def test_connected_by_default(self, settings):
        """Default (True) connects the handler."""
        rebac = dict(settings.REBAC)
        rebac.pop("sync_on_migrate", None)  # rely on default
        settings.REBAC = rebac

        post_migrate.disconnect(handle_post_migrate)

        from django_spicedb.conf import get_rebac_settings
        if get_rebac_settings().get("sync_on_migrate", True):
            post_migrate.connect(handle_post_migrate)

        assert _handler_is_connected()
        post_migrate.disconnect(handle_post_migrate)

    def test_connected_when_sync_on_migrate_true(self, settings):
        settings.REBAC = {**settings.REBAC, "sync_on_migrate": True}

        post_migrate.disconnect(handle_post_migrate)

        from django_spicedb.conf import get_rebac_settings
        if get_rebac_settings().get("sync_on_migrate", True):
            post_migrate.connect(handle_post_migrate)

        assert _handler_is_connected()
        post_migrate.disconnect(handle_post_migrate)

    def test_not_connected_when_sync_on_migrate_false(self, settings):
        settings.REBAC = {**settings.REBAC, "sync_on_migrate": False}

        post_migrate.disconnect(handle_post_migrate)

        from django_spicedb.conf import get_rebac_settings
        if get_rebac_settings().get("sync_on_migrate", True):
            post_migrate.connect(handle_post_migrate)

        assert not _handler_is_connected()


# -------------------------------------------------------------------
# 2. Once-per-migrate guard
# -------------------------------------------------------------------


class TestOnceGuard:
    """The handler should execute its body only once per migrate invocation."""

    @patch("django_spicedb.sync.migrate_hook.publish_schema")
    @patch("django_spicedb.sync.migrate_hook.get_adapter")
    @patch("django_spicedb.sync.migrate_hook.get_type_graph")
    def test_runs_only_once(self, mock_graph, mock_adapter, mock_publish):
        mock_graph.return_value = MagicMock(types={})
        mock_publish.return_value = "abc123"

        handle_post_migrate(sender=None)
        handle_post_migrate(sender=None)
        handle_post_migrate(sender=None)

        # publish_schema called exactly once
        mock_publish.assert_called_once()


# -------------------------------------------------------------------
# 3. Graceful skip on SpiceDB unreachable
# -------------------------------------------------------------------


class TestGracefulSkip:
    """SpiceDB failures should log a warning, not crash migrate."""

    @patch("django_spicedb.sync.migrate_hook.get_adapter")
    @patch("django_spicedb.sync.migrate_hook.get_type_graph")
    def test_unreachable_spicedb_logs_warning(self, mock_graph, mock_adapter, caplog):
        mock_adapter.side_effect = Exception("Connection refused")

        with caplog.at_level(logging.WARNING, logger="django_spicedb.sync.migrate_hook"):
            # Should NOT raise
            handle_post_migrate(sender=None)

        assert "could not publish schema" in caplog.text

    @patch("django_spicedb.sync.migrate_hook.publish_schema")
    @patch("django_spicedb.sync.migrate_hook.get_adapter")
    @patch("django_spicedb.sync.migrate_hook.get_type_graph")
    def test_publish_failure_skips_backfill(self, mock_graph, mock_adapter, mock_publish):
        mock_graph.return_value = MagicMock(types={"doc": MagicMock(model="x.Doc", bindings={"owner": {}})})
        mock_publish.side_effect = Exception("gRPC timeout")

        # Should NOT raise — and backfill should not be attempted
        with patch("django_spicedb.sync.migrate_hook.backfill_tuples") as mock_backfill:
            handle_post_migrate(sender=None)
            mock_backfill.assert_not_called()


# -------------------------------------------------------------------
# 4. Verbosity respected
# -------------------------------------------------------------------


class TestVerbosity:
    """The handler should respect verbosity kwarg from migrate."""

    @patch("django_spicedb.sync.migrate_hook.publish_schema")
    @patch("django_spicedb.sync.migrate_hook.get_adapter")
    @patch("django_spicedb.sync.migrate_hook.get_type_graph")
    def test_silent_at_verbosity_zero(self, mock_graph, mock_adapter, mock_publish, caplog):
        mock_graph.return_value = MagicMock(types={})
        mock_publish.return_value = "abc123"

        with caplog.at_level(logging.INFO, logger="django_spicedb.sync.migrate_hook"):
            handle_post_migrate(sender=None, verbosity=0)

        # At verbosity 0, no INFO messages should be logged
        info_messages = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_messages) == 0

    @patch("django_spicedb.sync.migrate_hook.publish_schema")
    @patch("django_spicedb.sync.migrate_hook.get_adapter")
    @patch("django_spicedb.sync.migrate_hook.get_type_graph")
    def test_logs_at_default_verbosity(self, mock_graph, mock_adapter, mock_publish, caplog):
        mock_graph.return_value = MagicMock(types={})
        mock_publish.return_value = "abc123"

        with caplog.at_level(logging.INFO, logger="django_spicedb.sync.migrate_hook"):
            handle_post_migrate(sender=None, verbosity=1)

        info_messages = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_messages) >= 1
        assert "published schema" in caplog.text
