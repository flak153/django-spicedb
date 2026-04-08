"""Tests for the write-token propagation contextvar and middleware."""

from __future__ import annotations

import asyncio
import contextvars

import pytest
from django.contrib.auth import get_user_model

import django_spicedb.conf as conf
from django_spicedb.middleware import WriteTokenMiddleware
from django_spicedb.runtime import (
    PermissionEvaluator,
    can,
    get_last_write_token,
    record_write_token,
    use_last_write_token,
)
from django_spicedb.sync import registry
from example_project.documents.models import Document, Folder, Workspace


User = get_user_model()


@pytest.fixture
def clean_token():
    """Ensure each test starts and ends with an empty write token."""
    with use_last_write_token():
        yield


@pytest.fixture
def rebac_setup(recording_adapter):
    """Refresh the sync registry against the recording adapter."""
    conf.reset_type_graph_cache()
    registry.refresh()
    yield
    conf.reset_type_graph_cache()
    registry.refresh()


# ---------------------------------------------------------------------------
# RebacModel.grant / revoke return tokens


@pytest.mark.django_db
def test_grant_returns_token(recording_adapter, clean_token):
    owner = User.objects.create_user(username="owner", password="pass")
    member = User.objects.create_user(username="member", password="pass")
    document = Document.objects.create(title="T", owner=owner)

    token = document.grant(member, "editor")
    assert token
    assert token.startswith("rec-")


@pytest.mark.django_db
def test_revoke_returns_token(recording_adapter, clean_token):
    owner = User.objects.create_user(username="owner", password="pass")
    member = User.objects.create_user(username="member", password="pass")
    document = Document.objects.create(title="T", owner=owner)

    token = document.revoke(member, "editor")
    assert token
    assert token.startswith("rec-")


@pytest.mark.django_db
def test_grant_records_into_contextvar(recording_adapter, clean_token):
    owner = User.objects.create_user(username="owner", password="pass")
    member = User.objects.create_user(username="member", password="pass")
    document = Document.objects.create(title="T", owner=owner)

    assert get_last_write_token() == ""
    returned = document.grant(member, "editor")
    assert get_last_write_token() == returned


# ---------------------------------------------------------------------------
# Evaluator auto-upgrades consistency when a write token is set


@pytest.mark.django_db
def test_can_upgrades_consistency_after_write(
    rebac_setup, recording_adapter, clean_token
):
    owner = User.objects.create_user(username="owner", password="pass")
    workspace = Workspace.objects.create(name="Acme")
    folder = Folder.objects.create(name="F", owner=owner)
    document = Document.objects.create(
        title="Spec", owner=owner, workspace=workspace, folder=folder
    )

    token = document.grant(owner, "view")
    assert token

    recording_adapter.check_calls.clear()
    recording_adapter.set_check_response(
        subject=f"user:{owner.pk}",
        relation="view",
        object_ref=f"document:{document.pk}",
        result=True,
        consistency=token,
    )

    assert can(owner, "view", document)
    assert len(recording_adapter.check_calls) == 1
    # The adapter saw consistency=<token>, not None
    call = recording_adapter.check_calls[0]
    assert call[3] == token


@pytest.mark.django_db
def test_can_does_not_upgrade_without_prior_write(
    rebac_setup, recording_adapter, clean_token
):
    owner = User.objects.create_user(username="owner", password="pass")
    workspace = Workspace.objects.create(name="Acme")
    folder = Folder.objects.create(name="F", owner=owner)
    document = Document.objects.create(
        title="Spec", owner=owner, workspace=workspace, folder=folder
    )
    # document creation triggered a sync write via on_commit inside the
    # outer transaction — by the time we reach here the contextvar reflects
    # real post-commit state, so clear it explicitly to simulate "no prior
    # write in this request".
    with use_last_write_token():
        recording_adapter.check_calls.clear()
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=False,
        )
        can(owner, "view", document)
        call = recording_adapter.check_calls[0]
        # consistency passed to adapter is None
        assert call[3] is None


@pytest.mark.django_db
def test_explicit_consistency_overrides_token(
    rebac_setup, recording_adapter, clean_token
):
    owner = User.objects.create_user(username="owner", password="pass")
    workspace = Workspace.objects.create(name="Acme")
    folder = Folder.objects.create(name="F", owner=owner)
    document = Document.objects.create(
        title="Spec", owner=owner, workspace=workspace, folder=folder
    )
    document.grant(owner, "view")

    recording_adapter.check_calls.clear()
    recording_adapter.set_check_response(
        subject=f"user:{owner.pk}",
        relation="view",
        object_ref=f"document:{document.pk}",
        result=True,
        consistency="fully_consistent",
    )
    evaluator = PermissionEvaluator(owner)
    evaluator.can("view", document, consistency="fully_consistent")
    call = recording_adapter.check_calls[0]
    assert call[3] == "fully_consistent"


# ---------------------------------------------------------------------------
# Contextvar isolation / scoping


def test_contextvar_isolation_between_contexts():
    # Start from a known-empty state so copied contexts don't inherit a
    # leaked token from prior tests in the same process.
    with use_last_write_token():
        ctx_a = contextvars.copy_context()
        ctx_b = contextvars.copy_context()

        def set_in_a():
            record_write_token("token-A")
            return get_last_write_token()

        def read_in_b():
            return get_last_write_token()

        assert ctx_a.run(set_in_a) == "token-A"
        # Context B never had the set call run inside it.
        assert ctx_b.run(read_in_b) == ""
        # And the outer context is unaffected by the ctx_a.run mutation.
        assert get_last_write_token() == ""


def test_use_last_write_token_restores_on_exit():
    record_write_token("outer")
    with use_last_write_token():
        assert get_last_write_token() == ""
        record_write_token("inner")
        assert get_last_write_token() == "inner"
    assert get_last_write_token() == "outer"
    # Clean up for any subsequent tests.
    with use_last_write_token():
        pass


def test_record_write_token_ignores_empty():
    with use_last_write_token():
        record_write_token("real")
        record_write_token("")
        assert get_last_write_token() == "real"


# ---------------------------------------------------------------------------
# Middleware


def test_middleware_sync_scopes_token():
    captured_inside: list[str] = []

    def fake_view(request):
        record_write_token("mw-sync")
        captured_inside.append(get_last_write_token())
        return "ok"

    # Preseed a token that should NOT be visible inside the request and
    # should be restored after it returns.
    with use_last_write_token():
        record_write_token("outer")
        middleware = WriteTokenMiddleware(fake_view)
        assert middleware(object()) == "ok"
        assert captured_inside == ["mw-sync"]
        # After the middleware returns, the outer context's token is restored.
        assert get_last_write_token() == "outer"


def test_middleware_async_scopes_token():
    captured_inside: list[str] = []

    async def fake_view(request):
        record_write_token("mw-async")
        captured_inside.append(get_last_write_token())
        return "ok"

    async def run():
        with use_last_write_token():
            record_write_token("outer")
            middleware = WriteTokenMiddleware(fake_view)
            result = await middleware(object())
            assert result == "ok"
            assert captured_inside == ["mw-async"]
            assert get_last_write_token() == "outer"

    asyncio.run(run())
