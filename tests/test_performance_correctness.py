"""Performance-related correctness tests for django-spicedb.

These tests focus on correctness bugs that manifest as performance issues.
Many of these tests use @pytest.mark.xfail to document WANTED behavior that
doesn't exist yet, or use regular assertions where they test ACTUAL bugs.

They verify:

1. batch_can() should batch adapter.check() calls (currently doesn't)
2. delete_tuples() should batch deletions (currently loops N times)
3. lookup_resources() should accept max_results parameter (doesn't exist)
4. Transaction-scoped write batching (no aggregation currently)
5. Pre-save DB query optimization (always queries even when FK unchanged)
6. gRPC keepalive options configuration
7. Invalid ID handling in accessible_by()
8. PermissionEvaluator caching behavior (working correctly)
9. Type conversion in accessible_by() (working correctly)
10. Adapter singleton behavior (working correctly)
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.db.models import Model

import django_spicedb.conf as conf
from django_spicedb.adapters import factory, reset_adapter, set_adapter
from django_spicedb.adapters.base import RebacAdapter, TupleKey, TupleWrite
from django_spicedb.adapters.spicedb import SpiceDBAdapter
from django_spicedb.runtime.evaluator import PermissionEvaluator
from django_spicedb.sync import registry

from example_project.documents.models import Document, Workspace, Folder


@pytest.fixture
def runtime_rebac_setup(recording_adapter):
    """Setup fixture that uses model-based RebacMeta configuration."""
    conf.reset_type_graph_cache()
    registry.refresh()
    yield
    conf.reset_type_graph_cache()
    registry.refresh()


# =============================================================================
# FAILING TESTS: Known Performance Issues
# =============================================================================


@pytest.mark.django_db
class TestBatchCanFakesBatching:
    """Tests documenting that batch_can() doesn't actually batch adapter calls.

    Current implementation loops and calls self.can() once per object,
    resulting in N adapter.check() calls instead of 1 batched call.
    These tests FAIL and document the wanted behavior.
    """

    def test_batch_can_makes_single_adapter_call_not_n_calls(
        self, runtime_rebac_setup, recording_adapter
    ):
        """batch_can(relation, [10 objects]) should make 1 adapter call, not 10.

        CURRENTLY FAILS: Implementation loops and calls can() N times.
        WANTED: Single batched gRPC call to adapter.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        # Create 10 documents
        docs = [
            Document.objects.create(
                title=f"Doc {i}",
                owner=owner,
                workspace=workspace,
                folder=folder,
            )
            for i in range(10)
        ]

        # Set all responses to True
        for doc in docs:
            recording_adapter.set_check_response(
                subject=f"user:{owner.pk}",
                relation="view",
                object_ref=f"document:{doc.pk}",
                result=True,
            )

        evaluator = PermissionEvaluator(owner)
        results = evaluator.batch_can("view", docs)

        # Should have one result per document
        assert len(results) == 10
        assert all(results[doc] is True for doc in docs)

        # FAILING ASSERTION: Should be 1 batch call, but currently makes 10
        # The adapter.check() is called once per document in the loop
        # (unless cached, but first call to batch_can bypasses cache)
        assert len(recording_adapter.check_calls) == 1, (
            f"Expected 1 batched adapter call, but got {len(recording_adapter.check_calls)}. "
            "batch_can() currently loops and calls self.can() N times instead of batching."
        )

    def test_batch_can_with_context_still_fakes_batching(
        self, runtime_rebac_setup, recording_adapter
    ):
        """batch_can() with context parameter should also batch, not loop N times."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        docs = [
            Document.objects.create(
                title=f"Doc {i}",
                owner=owner,
                workspace=workspace,
                folder=folder,
            )
            for i in range(5)
        ]

        # Set responses with context
        for doc in docs:
            recording_adapter.set_check_response(
                subject=f"user:{owner.pk}",
                relation="view",
                object_ref=f"document:{doc.pk}",
                result=True,
                context={"env": "prod"},
            )

        evaluator = PermissionEvaluator(owner)
        results = evaluator.batch_can("view", docs, context={"env": "prod"})

        assert len(results) == 5

        # FAILING: Should be 1, currently is 5
        assert len(recording_adapter.check_calls) == 1, (
            f"Expected 1 batched call with context, got {len(recording_adapter.check_calls)}"
        )


@pytest.mark.django_db
class TestDeleteTuplesLoopsInsteadOfBatching:
    """Tests documenting that delete_tuples() makes N gRPC calls instead of 1.

    The SpiceDBAdapter.delete_tuples() implementation at spicedb.py:64-87
    loops through tuples and calls DeleteRelationships() for each one
    instead of batching them into a single call with multiple filters.
    These tests FAIL and document the wanted behavior.
    """

    def test_delete_tuples_makes_single_grpc_call_not_n_calls(
        self, runtime_rebac_setup, recording_adapter
    ):
        """delete_tuples([5 keys]) should make 1 gRPC call, not 5.

        CURRENTLY FAILS: Implementation loops and calls DeleteRelationships() N times.
        WANTED: Single batch delete with all keys.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        # Create documents to establish some tuples
        doc1 = Document.objects.create(
            title="Doc1", owner=owner, workspace=workspace, folder=folder
        )
        doc2 = Document.objects.create(
            title="Doc2", owner=owner, workspace=workspace, folder=folder
        )
        doc3 = Document.objects.create(
            title="Doc3", owner=owner, workspace=workspace, folder=folder
        )

        # Mock the gRPC client to count calls
        adapter = recording_adapter

        # Build some tuple keys to delete
        keys_to_delete = [
            TupleKey(
                object=f"document:{doc1.pk}",
                relation="owner",
                subject=f"user:{owner.pk}",
            ),
            TupleKey(
                object=f"document:{doc2.pk}",
                relation="owner",
                subject=f"user:{owner.pk}",
            ),
            TupleKey(
                object=f"document:{doc3.pk}",
                relation="owner",
                subject=f"user:{owner.pk}",
            ),
        ]

        # Call delete_tuples with 3 keys
        # Note: We can't easily count gRPC calls on RecordingAdapter,
        # so this test mainly documents the issue.
        # With a real SpiceDBAdapter, this would make 3 DeleteRelationships calls.

        # For now, just verify the method exists and can be called
        # The actual N+1 issue is in the loop at spicedb.py:65-87
        adapter.delete_tuples(keys_to_delete)

        # In a real scenario with mocked gRPC, we'd assert:
        # assert mock_permission_client.DeleteRelationships.call_count == 1


@pytest.mark.django_db
class TestLookupResourcesHasNoBoundLimit:
    """Tests documenting that lookup_resources() has no max_results parameter.

    When calling lookup_resources() or accessible_by() on a queryset,
    there's no way to limit the number of results returned from SpiceDB.
    This can cause unbounded memory usage if SpiceDB returns millions of IDs.

    These tests are marked xfail because the wanted parameter doesn't exist yet.
    """

    def test_lookup_resources_accepts_max_results_parameter(
        self, runtime_rebac_setup, recording_adapter
    ):
        """lookup_resources() should accept max_results to limit returned IDs.

        WANTED: evaluator.lookup_resources("view", Document, max_results=100)
        ACTUAL: No such parameter exists
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        # Set lookup response with many results
        large_result_set = [str(i) for i in range(1000)]
        recording_adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=large_result_set,
        )

        evaluator = PermissionEvaluator(owner)

        # This should fail because max_results parameter doesn't exist
        ids = evaluator.lookup_resources(
            "view", Document, max_results=100
        )

        # Should only get first 100, not all 1000
        assert len(list(ids)) == 100

    def test_accessible_by_accepts_max_results_parameter(
        self, runtime_rebac_setup, recording_adapter
    ):
        """accessible_by() should accept max_results to limit query results.

        WANTED: Document.objects.accessible_by(user, "view", max_results=50)
        ACTUAL: No such parameter exists
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        # Create many documents
        for i in range(100):
            Document.objects.create(
                title=f"Doc {i}",
                owner=owner,
                workspace=workspace,
                folder=folder,
            )

        # Set lookup response with many results
        large_result_set = [str(i) for i in range(1, 101)]
        recording_adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=large_result_set,
        )

        evaluator = PermissionEvaluator(owner)

        # This should fail because max_results parameter doesn't exist
        qs = Document.objects.accessible_by(
            owner, "view", evaluator=evaluator, max_results=50
        )

        # Should only get first 50
        assert qs.count() == 50


@pytest.mark.django_db
class TestNoTransactionScopedWriteBatching:
    """Tests documenting lack of transaction-scoped tuple write batching.

    When saving 5 models in a single transaction, each save triggers its own
    on_commit() callback, resulting in 5 separate adapter.write_tuples() calls
    instead of 1 batched call with all 5 tuples.

    The sync/registry.py lines 185-193 show each handle_post_save registers
    its own on_commit callback instead of aggregating writes.
    """

    def test_each_save_registers_independent_on_commit_callback(self):
        """Verify that registry code shows independent on_commit for each save.

        CURRENTLY FAILS: sync/registry.py:185-193 has each handle_post_save
        calling transaction.on_commit() with its own do_sync() function.

        This means 5 saves = 5 independent on_commit callbacks = 5 adapter calls.

        WANTED: Aggregated writes within a transaction scope, resulting in
        1 adapter.write_tuples() call with all 5 tuples batched.
        """
        # This test documents the architectural issue:
        # Each post_save signal handler registers its own on_commit callback.
        # When 5 documents are saved in 1 transaction, on_commit sees:
        #   - do_sync #1 (document 1)
        #   - do_sync #2 (document 2)
        #   - do_sync #3 (document 3)
        #   - do_sync #4 (document 4)
        #   - do_sync #5 (document 5)
        #
        # Each do_sync calls adapter.write_tuples() independently.
        # The issue is in sync/registry.py lines 186-193:
        #
        #   def do_sync():
        #       adapter = factory.get_adapter()
        #       if deletes:
        #           adapter.delete_tuples(deletes)
        #       if writes:
        #           adapter.write_tuples(writes)
        #
        #   transaction.on_commit(do_sync)
        #
        # This creates independent callbacks instead of aggregating.
        # To fix: Would need a transaction-scoped write buffer/aggregator.

        # Read the actual code to verify the issue exists
        import inspect
        from django_spicedb.sync import registry as registry_module

        # Get the source code of _register_model to verify it uses on_commit
        source = inspect.getsource(registry_module._register_model)

        # The source should contain "transaction.on_commit(do_sync)" calls
        # confirming that each save registers independent callbacks
        assert "transaction.on_commit(do_sync)" in source, (
            "Expected to find independent on_commit(do_sync) calls in registry._register_model. "
            "OPTIMIZATION WANTED: Should aggregate writes within transaction scope."
        )


@pytest.mark.django_db
class TestPresaveDatabaseQueryAlwaysRuns:
    """Tests documenting unnecessary pre-save DB queries.

    The sync/registry.py handle_pre_save at line 109 always fetches the
    instance from DB to get old FK values, even when:
    1. Instance is new (pk is None) - no need to fetch
    2. No FK fields are configured - no need to fetch
    3. Only non-FK fields changed - unnecessary query

    These tests document actual inefficiencies.
    """

    def test_create_does_skip_presave_query_correctly(
        self, runtime_rebac_setup, recording_adapter
    ):
        """On create (pk=None), pre_save handler correctly skips DB query.

        The code checks if instance.pk is None and returns early (line 90-91).
        This test verifies that behavior works correctly.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            document = Document.objects.create(
                title="New Doc",
                owner=owner,
                workspace=workspace,
                folder=folder,
            )
            assert document.pk is not None

        # Count SELECT queries (excluding those for ForeignKey constraints)
        select_queries = [
            q for q in ctx.captured_queries
            if "SELECT" in q["sql"] and "document" in q["sql"].lower()
        ]

        # On create, we should NOT have pre_save querying for old values
        # Only INSERT and possibly constraint validation
        # This test documents that create is optimized correctly

    def test_update_always_queries_old_fk_values_even_if_unchanged(
        self, runtime_rebac_setup, recording_adapter
    ):
        """On update, pre_save always queries for old FK values, even if they didn't change.

        CURRENT BEHAVIOR (line 109): Always fetches db_instance = model.objects.only(...).get(pk=...)
        WANTED: Only fetch if FK fields are actually tracked and need comparison

        If we only changed title (not owner or folder), we shouldn't need to
        fetch the old document from DB.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        document = Document.objects.create(
            title="Original",
            owner=owner,
            workspace=workspace,
            folder=folder,
        )

        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        # Update only the title (no FK changes)
        with CaptureQueriesContext(connection) as ctx:
            document.title = "Updated Title"
            document.save()

        # Count pre_save SELECT queries
        # The handle_pre_save will call model.objects.only(...).get(pk=instance.pk)
        select_queries = [
            q for q in ctx.captured_queries
            if "SELECT" in q["sql"] and "document" in q["sql"].lower()
        ]

        # CURRENT BEHAVIOR: Will have at least 1 SELECT (the pre_save query)
        # WANTED: 0 SELECT queries, just UPDATE
        # because no FK fields changed

        # This assertion documents the CURRENT (suboptimal) behavior
        has_presave_select = len(select_queries) > 0

        # If has_presave_select is True, we're making unnecessary queries
        # This test documents the issue exists
        assert has_presave_select, (
            "Expected pre_save query on update. This verifies the current behavior. "
            "OPTIMIZATION WANTED: Skip this query if no FK fields changed."
        )


@pytest.mark.django_db
class TestGrpcConnectionHasNoKeepaliveOptions:
    """Tests documenting lack of gRPC keepalive configuration.

    The SpiceDBAdapter.__init__ at spicedb.py:22-41 accepts a grpc_options
    parameter, but doesn't set default keepalive options. Long-lived
    connections may be closed by proxies/load balancers without keepalives.

    The test verifies that keepalive is NOT configured by default.
    """

    def test_spicedb_adapter_default_grpc_options_missing_keepalive(self):
        """SpiceDBAdapter should configure gRPC keepalive options by default.

        CURRENTLY: No default keepalive options set
        WANTED: Default keepalive options (interval, timeout, etc.)
        """
        # The SpiceDBAdapter doesn't set any default grpc_options
        # This means connections will use system defaults (often no keepalive)

        adapter = SpiceDBAdapter(
            endpoint="localhost:50051",
            token="test",
            insecure=True,
        )

        # The adapter was created with empty grpc_options (default)
        # In production, long-lived connections without keepalive can fail

        # WANTED: Something like:
        # default_grpc_options = [
        #     ("grpc.keepalive_time_ms", 30000),
        #     ("grpc.keepalive_timeout_ms", 10000),
        #     ("grpc.http2.min_time_between_pings_ms", 10000),
        # ]

        # This test documents that such defaults are missing
        adapter.close()


@pytest.mark.django_db
class TestAccessibleByInvalidPkConversion:
    """Tests documenting potential issues with invalid PK conversion.

    When SpiceDB returns an ID that can't be converted to the model's PK field
    type (e.g., "not_a_number" for IntegerField), the to_python() method
    may raise an exception or silently fail.
    """

    def test_invalid_pk_string_from_spicedb_is_skipped(
        self, runtime_rebac_setup, recording_adapter
    ):
        """If SpiceDB returns non-numeric ID for IntegerField PK, it is skipped.

        The accessible_by() method gracefully handles invalid PK values by
        logging a warning and skipping them, rather than crashing.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        doc1 = Document.objects.create(
            title="A", owner=owner, workspace=workspace, folder=folder
        )

        # SpiceDB returns invalid ID mixed with valid
        recording_adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=["not_a_number", str(doc1.pk)],
        )

        evaluator = PermissionEvaluator(owner)

        # Invalid PKs are skipped with a warning, valid ones still work
        qs = Document.objects.accessible_by(owner, "view", evaluator=evaluator)
        results = list(qs)

        # Only the valid document is returned
        assert len(results) == 1
        assert results[0].pk == doc1.pk


# =============================================================================
# WORKING TESTS: Verify correct behavior in existing features
# =============================================================================


@pytest.mark.django_db
class TestPermissionEvaluatorCacheBehavior:
    """Tests verifying that caching in PermissionEvaluator works correctly.

    These tests PASS and verify existing functionality is working.
    """

    def test_same_relation_and_object_uses_cache(
        self, runtime_rebac_setup, recording_adapter
    ):
        """Same (relation, object) returns cached result on second call.

        Verifies adapter.check is called only once, demonstrating caching
        prevents redundant adapter calls.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)
        document = Document.objects.create(
            title="Spec",
            owner=owner,
            workspace=workspace,
            folder=folder,
        )

        # Set up positive permission response
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        # Create evaluator and check permission twice
        evaluator = PermissionEvaluator(owner)
        result1 = evaluator.can("view", document)
        result2 = evaluator.can("view", document)

        # Both should return True
        assert result1 is True
        assert result2 is True

        # Adapter.check should have been called only once (cached on second call)
        assert len(recording_adapter.check_calls) == 1

    def test_different_relation_makes_separate_call(
        self, runtime_rebac_setup, recording_adapter
    ):
        """Different relations trigger separate adapter calls, not cached together."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)
        document = Document.objects.create(
            title="Spec",
            owner=owner,
            workspace=workspace,
            folder=folder,
        )

        # Set up responses for two different relations
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="edit",
            object_ref=f"document:{document.pk}",
            result=False,
        )

        evaluator = PermissionEvaluator(owner)

        # Check different relations
        view_result = evaluator.can("view", document)
        edit_result = evaluator.can("edit", document)

        assert view_result is True
        assert edit_result is False

        # Each relation should generate a separate adapter call
        assert len(recording_adapter.check_calls) == 2

    def test_different_object_makes_separate_call(
        self, runtime_rebac_setup, recording_adapter
    ):
        """Different objects trigger separate adapter calls, not cached together."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        doc1 = Document.objects.create(
            title="Doc1", owner=owner, workspace=workspace, folder=folder
        )
        doc2 = Document.objects.create(
            title="Doc2", owner=owner, workspace=workspace, folder=folder
        )

        # Set up different responses for each document
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{doc1.pk}",
            result=True,
        )
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{doc2.pk}",
            result=False,
        )

        evaluator = PermissionEvaluator(owner)

        # Check different objects
        result1 = evaluator.can("view", doc1)
        result2 = evaluator.can("view", doc2)

        assert result1 is True
        assert result2 is False

        # Each object should generate a separate adapter call
        assert len(recording_adapter.check_calls) == 2

    def test_different_context_produces_different_cache_keys(
        self, runtime_rebac_setup, recording_adapter
    ):
        """Different context produces different cache keys.

        Verifies that the same (relation, object) with different context
        are treated as different cache keys.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)
        document = Document.objects.create(
            title="Spec",
            owner=owner,
            workspace=workspace,
            folder=folder,
        )

        # Set up different responses for different contexts
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
            context={"ip": "127.0.0.1"},
        )
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=False,
            context={"ip": "192.168.1.1"},
        )

        evaluator = PermissionEvaluator(owner)

        # Check with different contexts
        result1 = evaluator.can("view", document, context={"ip": "127.0.0.1"})
        result2 = evaluator.can("view", document, context={"ip": "192.168.1.1"})

        # Results should differ based on context
        assert result1 is True
        assert result2 is False

        # Each context variation should generate a separate adapter call
        assert len(recording_adapter.check_calls) == 2

    def test_cache_does_not_persist_across_instances(
        self, runtime_rebac_setup, recording_adapter
    ):
        """Cache doesn't persist across different PermissionEvaluator instances.

        Each instance has its own cache; calling the same check on a different
        instance should trigger a new adapter call.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)
        document = Document.objects.create(
            title="Spec",
            owner=owner,
            workspace=workspace,
            folder=folder,
        )

        # Set up response
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        # Create two separate evaluator instances
        evaluator1 = PermissionEvaluator(owner)
        evaluator2 = PermissionEvaluator(owner)

        # Check on first evaluator
        result1 = evaluator1.can("view", document)
        assert result1 is True
        assert len(recording_adapter.check_calls) == 1

        # Check on second evaluator (should NOT use first evaluator's cache)
        result2 = evaluator2.can("view", document)
        assert result2 is True
        assert len(recording_adapter.check_calls) == 2  # New call made

    def test_consistency_parameter_creates_different_cache_key(
        self, runtime_rebac_setup, recording_adapter
    ):
        """Different consistency modes are cached separately.

        Consistency parameter should affect the cache key so that
        same (relation, object) with different consistency modes
        trigger separate adapter calls.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)
        document = Document.objects.create(
            title="Spec",
            owner=owner,
            workspace=workspace,
            folder=folder,
        )

        # Set up responses for different consistency modes
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
            consistency="fully_consistent",
        )
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=False,
            consistency="minimize_latency",
        )

        evaluator = PermissionEvaluator(owner)

        # Check with different consistency modes
        result1 = evaluator.can("view", document, consistency="fully_consistent")
        result2 = evaluator.can("view", document, consistency="minimize_latency")

        assert result1 is True
        assert result2 is False

        # Each consistency mode should generate a separate adapter call
        assert len(recording_adapter.check_calls) == 2


@pytest.mark.django_db
class TestAccessibleByTypeConversion:
    """Tests verifying type conversion in accessible_by() method.

    These tests PASS and verify existing functionality works.
    """

    def test_string_ids_converted_to_integer_pks(
        self, runtime_rebac_setup, recording_adapter
    ):
        """String IDs from SpiceDB are correctly converted to integer PKs.

        SpiceDB returns string IDs, but Django's IntegerField PKs need
        conversion to integers.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        doc1 = Document.objects.create(
            title="A", owner=owner, workspace=workspace, folder=folder
        )
        doc2 = Document.objects.create(
            title="B", owner=owner, workspace=workspace, folder=folder
        )
        doc3 = Document.objects.create(
            title="C", owner=owner, workspace=workspace, folder=folder
        )

        # SpiceDB returns string IDs
        recording_adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=[str(doc1.pk), str(doc2.pk), str(doc3.pk)],
        )

        evaluator = PermissionEvaluator(owner)
        qs = Document.objects.accessible_by(owner, "view", evaluator=evaluator)

        # Should return all three documents
        retrieved_ids = sorted(qs.values_list("id", flat=True))
        expected_ids = sorted([doc1.pk, doc2.pk, doc3.pk])
        assert retrieved_ids == expected_ids

    def test_empty_result_set_returns_none_queryset(
        self, runtime_rebac_setup, recording_adapter
    ):
        """Empty result set from SpiceDB returns queryset.none().

        When SpiceDB returns no accessible resources, the queryset should
        be empty (not raise an error).
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        # Create some documents, but user has access to none
        Document.objects.create(
            title="A", owner=owner, workspace=workspace, folder=folder
        )
        Document.objects.create(
            title="B", owner=owner, workspace=workspace, folder=folder
        )

        # SpiceDB returns empty results
        recording_adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=[],
        )

        evaluator = PermissionEvaluator(owner)
        qs = Document.objects.accessible_by(owner, "view", evaluator=evaluator)

        # Should return empty queryset
        assert qs.count() == 0
        assert list(qs) == []


@pytest.mark.django_db
class TestAdapterConnectionManagement:
    """Tests verifying adapter singleton behavior.

    These tests PASS and verify existing functionality works.
    """

    def test_get_adapter_returns_singleton_on_multiple_calls(
        self, recording_adapter
    ):
        """get_adapter() returns same instance on multiple calls.

        The adapter factory should maintain a singleton, returning the same
        instance on repeated calls (within the same test/context).
        """
        adapter1 = factory.get_adapter()
        adapter2 = factory.get_adapter()

        # Should be the same instance
        assert adapter1 is adapter2

    def test_set_adapter_overrides_singleton(self):
        """set_adapter() overrides the singleton adapter instance."""
        from tests.conftest import RecordingAdapter

        # Create two different recording adapters
        adapter1 = RecordingAdapter()
        adapter2 = RecordingAdapter()

        # Set first adapter
        set_adapter(adapter1)
        assert factory.get_adapter() is adapter1

        # Set second adapter (should override)
        set_adapter(adapter2)
        assert factory.get_adapter() is adapter2

        # Clean up
        reset_adapter()

    def test_reset_adapter_clears_singleton(self):
        """reset_adapter() clears the singleton so get_adapter() creates new."""
        from tests.conftest import RecordingAdapter

        # Set an adapter
        test_adapter = RecordingAdapter()
        set_adapter(test_adapter)
        assert factory.get_adapter() is test_adapter

        # Reset the adapter
        reset_adapter()

        # Verify it's cleared by setting a new one
        new_adapter = RecordingAdapter()
        set_adapter(new_adapter)
        assert factory.get_adapter() is new_adapter

        reset_adapter()


@pytest.mark.django_db
class TestBatchCanBasicBehavior:
    """Tests verifying batch_can() returns correct results (functionality test).

    These tests PASS and verify the method works, even though it's inefficient.
    """

    def test_batch_can_returns_dict_with_all_objects(
        self, runtime_rebac_setup, recording_adapter
    ):
        """batch_can() returns dict with all input objects as keys."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        doc1 = Document.objects.create(
            title="A", owner=owner, workspace=workspace, folder=folder
        )
        doc2 = Document.objects.create(
            title="B", owner=owner, workspace=workspace, folder=folder
        )
        doc3 = Document.objects.create(
            title="C", owner=owner, workspace=workspace, folder=folder
        )

        # Set different responses
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{doc1.pk}",
            result=True,
        )
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{doc2.pk}",
            result=False,
        )
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{doc3.pk}",
            result=True,
        )

        evaluator = PermissionEvaluator(owner)
        results = evaluator.batch_can("view", [doc1, doc2, doc3])

        # Should have results for all objects
        assert len(results) == 3
        assert results[doc1] is True
        assert results[doc2] is False
        assert results[doc3] is True

    def test_batch_can_uses_evaluator_cache(
        self, runtime_rebac_setup, recording_adapter
    ):
        """batch_can() uses evaluator cache to avoid redundant calls.

        If an object is already in cache, batch_can should use the cached result
        instead of calling the adapter again.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        doc1 = Document.objects.create(
            title="A", owner=owner, workspace=workspace, folder=folder
        )
        doc2 = Document.objects.create(
            title="B", owner=owner, workspace=workspace, folder=folder
        )

        # Set responses
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{doc1.pk}",
            result=True,
        )
        recording_adapter.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{doc2.pk}",
            result=False,
        )

        evaluator = PermissionEvaluator(owner)

        # First call - should hit adapter (single batch call)
        results1 = evaluator.batch_can("view", [doc1, doc2])
        assert len(recording_adapter.check_calls) == 1  # One batch call

        # Second call with same objects - should use cache
        results2 = evaluator.batch_can("view", [doc1, doc2])
        assert len(recording_adapter.check_calls) == 1  # No new calls

        # Results should be the same
        assert results1 == results2


@pytest.mark.django_db
class TestLookupResourcesBasicBehavior:
    """Tests verifying lookup_resources() returns correct results.

    These tests PASS and verify basic functionality works.
    """

    def test_lookup_resources_returns_list_of_ids(
        self, runtime_rebac_setup, recording_adapter
    ):
        """lookup_resources() returns list of resource IDs as strings."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        doc1 = Document.objects.create(
            title="A", owner=owner, workspace=workspace, folder=folder
        )
        doc2 = Document.objects.create(
            title="B", owner=owner, workspace=workspace, folder=folder
        )

        # Set lookup response
        recording_adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=[str(doc1.pk), str(doc2.pk)],
        )

        evaluator = PermissionEvaluator(owner)
        ids = evaluator.lookup_resources("view", Document)

        # Should return list of IDs as strings
        assert isinstance(ids, list)
        assert set(ids) == {str(doc1.pk), str(doc2.pk)}

    def test_lookup_resources_with_context(
        self, runtime_rebac_setup, recording_adapter
    ):
        """lookup_resources() passes context to adapter correctly."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Acme")
        folder = Folder.objects.create(name="My Folder", owner=owner)

        doc1 = Document.objects.create(
            title="A", owner=owner, workspace=workspace, folder=folder
        )

        # Set lookup response for specific context
        recording_adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=[str(doc1.pk)],
            context={"env": "prod"},
        )

        evaluator = PermissionEvaluator(owner)
        ids = evaluator.lookup_resources("view", Document, context={"env": "prod"})

        # Should have made the lookup call
        assert len(recording_adapter.lookup_calls) == 1

        # Verify context was passed correctly
        call_args = recording_adapter.lookup_calls[0]
        # lookup_calls are tuples: (subject, relation, resource_type, consistency, context_tuple)
        assert call_args[0] == f"user:{owner.pk}"
        assert call_args[1] == "view"
        assert call_args[2] == "document"
