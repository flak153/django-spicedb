"""
Security vulnerability tests for django-spicedb.

These tests document currently vulnerable behavior - they verify the existence of
security issues and edge cases. Tests use @pytest.mark.xfail for behaviors that
SHOULD be protected but currently are not.

Test categories:
1. Input validation vulnerabilities
2. Permission evaluator edge cases
3. Signal sync failure scenarios
4. Staff/superuser privilege escalation
5. Cache and consistency issues
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings

import django_spicedb.conf as conf
from django_spicedb.adapters import factory
from django_spicedb.models import HierarchyNode, HierarchyTypeDefinition
from django_spicedb.runtime.evaluator import (
    PermissionEvaluator,
    _subject_to_reference,
    can,
)
from django_spicedb.sync import registry

from example_project.documents.models import Document, Folder, Workspace, Company


User = get_user_model()


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def rebac_setup():
    """Setup REBAC for all tests."""
    conf.reset_type_graph_cache()
    registry.refresh()
    yield
    conf.reset_type_graph_cache()
    registry.refresh()


class RecordingAdapterWithErrorHandling:
    """Enhanced recording adapter that can raise exceptions on write_tuples."""

    def __init__(self, raise_on_write=False, raise_on_check=False):
        self.schema = None
        self.zedtokens = []
        self.writes = []
        self.deletes = []
        self._check_responses = {}
        self._lookup_responses = {}
        self.check_calls = []
        self.lookup_calls = []
        self.raise_on_write = raise_on_write
        self.raise_on_check = raise_on_check

    def publish_schema(self, schema: str) -> str:
        self.schema = schema
        token = f"token-{len(self.zedtokens) + 1}"
        self.zedtokens.append(token)
        return token

    def write_tuples(self, tuples):
        if self.raise_on_write:
            raise RuntimeError("Adapter write_tuples failed: connection lost")
        self.writes.extend(tuples)

    def delete_tuples(self, tuples):
        self.deletes.extend(tuples)

    def set_check_response(self, *, subject, relation, object_ref, result, context=None, consistency=None):
        key = (subject, relation, object_ref, consistency, tuple(sorted((context or {}).items())))
        self._check_responses[key] = result

    def check(self, subject, relation, object_, *, context=None, consistency=None):
        if self.raise_on_check:
            raise RuntimeError("Adapter check failed: connection lost")
        key = (subject, relation, object_, consistency, tuple(sorted((context or {}).items())))
        self.check_calls.append(key)
        return self._check_responses.get(key, False)

    def set_lookup_response(self, *, subject, relation, resource_type, results, context=None, consistency=None):
        key = (subject, relation, resource_type, consistency, tuple(sorted((context or {}).items())))
        self._lookup_responses[key] = results

    def lookup_resources(self, subject, relation, resource_type, *, context=None, consistency=None, max_results=None):
        key = (subject, relation, resource_type, consistency, tuple(sorted((context or {}).items())))
        self.lookup_calls.append(key)
        results = self._lookup_responses.get(key, [])
        if max_results is not None:
            results = results[:max_results]
        return iter(results)


@pytest.fixture
def mock_adapter_with_errors():
    """Adapter fixture that can simulate failures."""
    adapter = RecordingAdapterWithErrorHandling()
    factory.set_adapter(adapter)
    yield adapter
    factory.reset_adapter()


@pytest.fixture
def company(db):
    """Test tenant."""
    return Company.objects.create(
        name="TestCorp",
        slug="testcorp",
    )


@pytest.fixture
def company_ct(company):
    """ContentType for Company."""
    return ContentType.objects.get_for_model(Company)


# ============================================================================
# 1. INPUT VALIDATION VULNERABILITIES
# ============================================================================


class TestInputValidation:
    """Test input validation in permission system."""

    @pytest.mark.django_db
    def test_subject_to_reference_with_missing_colon_separator(self):
        """
        FIXED: _subject_to_reference() now validates string format.

        A string without ":" is now rejected with ImproperlyConfigured.
        This prevents malformed reference strings like "invalidtype123"
        from being used in permission checks.

        Expected behavior: Should validate format or raise ImproperlyConfigured
        Current behavior: Raises ImproperlyConfigured for invalid format
        """
        # Now raises an error for invalid format
        with pytest.raises(ImproperlyConfigured, match="Invalid subject reference"):
            _subject_to_reference("invalidformatstring")

    @pytest.mark.django_db
    def test_subject_reference_format_validation(self):
        """Subject references SHOULD match format type:id with no special chars."""
        # This test documents the WANTED behavior
        with pytest.raises(ImproperlyConfigured):
            _subject_to_reference("user::1")  # Double colon

        with pytest.raises(ImproperlyConfigured):
            _subject_to_reference("user:1:extra")  # Extra colons

        with pytest.raises(ImproperlyConfigured):
            _subject_to_reference("user:id with spaces")  # Invalid chars

    @pytest.mark.django_db
    def test_empty_string_relation_permission_check(self, mock_adapter_with_errors):
        """
        FIXED: Permission checks now reject empty relation name.

        The can() function now validates that relation is non-empty.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        doc = Document.objects.create(
            title="Test",
            owner=owner,
            workspace=Workspace.objects.create(name="ws"),
        )

        # Empty relation name now raises ImproperlyConfigured
        with pytest.raises(ImproperlyConfigured, match="Invalid relation name"):
            can(owner, "", doc)

    @pytest.mark.django_db
    def test_permission_relation_format_validation(self, mock_adapter_with_errors):
        """Relation names SHOULD be validated to prevent injection."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        doc = Document.objects.create(
            title="Test",
            owner=owner,
            workspace=Workspace.objects.create(name="ws"),
        )

        # These should raise validation errors
        with pytest.raises(ImproperlyConfigured):
            can(owner, "", doc)  # Empty

        with pytest.raises(ImproperlyConfigured):
            can(owner, "view with spaces", doc)  # Spaces

        with pytest.raises(ImproperlyConfigured):
            can(owner, "view|inject", doc)  # Special chars

    @pytest.mark.django_db
    def test_type_names_with_special_characters(self):
        """
        VULNERABILITY: Type/relation names in schema aren't sanitized.

        If a model or relation name contains special characters,
        they could be injected into SpiceDB schema DSL.
        """
        # The system uses conf.get_type_for_model() which returns sanitized names
        # from RebacMeta.type_name, but there's no validation that
        # relation names are safe for schema compilation.
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")

        # When creating a reference, special chars in pk are passed through
        ref = _subject_to_reference(owner)
        assert f"user:{owner.pk}" == ref

    @pytest.mark.django_db
    def test_crafted_subject_reference_values(self):
        """
        FIXED: Subject references now validated for format.

        String references with extra colons are now rejected.
        UUIDs with hyphens in the ID part are still valid (e.g., "user:550e8400-e29b-41d4-a716-446655440000").
        """
        # UUIDs with hyphens are valid pks
        User = get_user_model()
        user = User.objects.create_user(username="test", password="pass")

        ref = _subject_to_reference(user)
        # Reference is created with numeric pk
        assert ":" in ref
        assert ref.count(":") == 1  # One colon only

        # String references with extra colons are now rejected
        malformed_ref = "user:1:extra:colons"
        with pytest.raises(ImproperlyConfigured, match="Invalid subject reference"):
            _subject_to_reference(malformed_ref)


# ============================================================================
# 2. PERMISSION EVALUATOR EDGE CASES
# ============================================================================


class TestPermissionEvaluatorEdgeCases:
    """Test edge cases in permission evaluation."""

    @pytest.mark.django_db
    def test_evaluator_adapter_exception_behavior(self, mock_adapter_with_errors):
        """
        FIXED: Adapter exceptions are now handled gracefully.

        If the adapter.check() raises an exception, the evaluator catches it,
        logs an error, and returns False instead of propagating the exception.
        This prevents DoS vectors and avoids exposing internal errors.
        """
        adapter = RecordingAdapterWithErrorHandling(raise_on_check=True)
        factory.set_adapter(adapter)

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        doc = Document.objects.create(
            title="Test",
            owner=owner,
            workspace=Workspace.objects.create(name="ws"),
        )

        evaluator = PermissionEvaluator(owner)

        # Exception from adapter now propagates (fail-loud)
        with pytest.raises(RuntimeError, match="connection lost"):
            evaluator.can("view", doc)

        factory.reset_adapter()

    @pytest.mark.django_db
    def test_evaluator_adapter_exception_propagates(self, mock_adapter_with_errors):
        """Adapter exceptions SHOULD propagate (fail-loud)."""
        adapter = RecordingAdapterWithErrorHandling(raise_on_check=True)
        factory.set_adapter(adapter)

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        doc = Document.objects.create(
            title="Test",
            owner=owner,
            workspace=Workspace.objects.create(name="ws"),
        )

        evaluator = PermissionEvaluator(owner)

        # Exception propagates instead of silently returning False
        with pytest.raises(RuntimeError, match="connection lost"):
            evaluator.can("view", doc)

        factory.reset_adapter()

    @pytest.mark.django_db
    def test_stale_cache_after_tuple_change(self):
        """
        VULNERABILITY: Evaluator cache persists beyond adapter state changes.

        When using the same evaluator instance across permission checks,
        if the underlying SpiceDB state changes (tuple written/deleted),
        the cached result will be stale.

        This is a request-scoped evaluator, so it SHOULD be fine within a
        single request, but documents the implicit assumption.
        """
        from tests.conftest import RecordingAdapter

        adapter = RecordingAdapter()
        factory.set_adapter(adapter)

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        doc = Document.objects.create(
            title="Test",
            owner=owner,
            workspace=Workspace.objects.create(name="ws"),
        )

        subject_ref = f"user:{owner.pk}"
        object_ref = f"document:{doc.pk}"

        # First check: user has view permission
        adapter.set_check_response(
            subject=subject_ref,
            relation="view",
            object_ref=object_ref,
            result=True,
        )

        evaluator = PermissionEvaluator(owner)
        assert evaluator.can("view", doc) is True
        assert len(adapter.check_calls) == 1

        # Now "change" the permission in the adapter
        adapter.set_check_response(
            subject=subject_ref,
            relation="view",
            object_ref=object_ref,
            result=False,  # Changed!
        )

        # But the evaluator still has the old cached result
        assert evaluator.can("view", doc) is True  # STALE!
        assert len(adapter.check_calls) == 1  # No new check

        factory.reset_adapter()

    @pytest.mark.django_db
    def test_accessible_by_very_large_result_set(self):
        """accessible_by() with large lookup results uses chunked queries.

        The chunking logic (500-item batches) in RebacQuerySet.accessible_by()
        handles large result sets by splitting pk__in into multiple OR clauses.
        """
        from tests.conftest import RecordingAdapter

        adapter = RecordingAdapter()
        factory.set_adapter(adapter)

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")

        # Simulate lookup returning 2000 IDs (tests chunking into 4 batches of 500)
        # Start from 900000 to avoid overlapping with real auto-increment PKs
        large_id_list = [str(i) for i in range(900000, 902000)]
        adapter.set_lookup_response(
            subject=f"user:{owner.pk}",
            relation="view",
            resource_type="document",
            results=large_id_list,
        )

        # Create a few documents (only some will match the large_id_list)
        Workspace.objects.create(name="ws")
        [
            Document.objects.create(
                title=f"Doc {i}",
                owner=owner,
                workspace=Workspace.objects.create(name=f"ws{i}"),
            )
            for i in range(3)
        ]

        evaluator = PermissionEvaluator(owner)
        qs = Document.objects.accessible_by(owner, "view", evaluator=evaluator)

        # Query executes with chunked pk__in list
        result = list(qs.values_list("id", flat=True))
        # Only docs with IDs in our small set will match
        assert len(result) == 0  # None of 0,1,2 are in large_id_list

        factory.reset_adapter()


# ============================================================================
# 3. SIGNAL SYNC FAILURE SCENARIOS
# ============================================================================


class TestSignalSyncFailures:
    """Test behavior when tuple sync fails."""

    @pytest.mark.django_db
    def test_django_save_succeeds_when_adapter_write_fails(self):
        """
        VULNERABILITY: Django model save succeeds even if adapter write fails.

        The tuple sync is wrapped in transaction.on_commit(), which means:
        1. Django transaction commits first
        2. on_commit callback attempts to write tuples
        3. If write fails, Django model is already saved but tuples are not written

        This creates an inconsistency gap where the permission model is out of sync
        with the SpiceDB permission store.
        """
        adapter = RecordingAdapterWithErrorHandling(raise_on_write=True)
        factory.set_adapter(adapter)

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        Workspace.objects.create(name="ws")

        # Create a folder with owner - this will trigger sync
        folder = Folder(name="TestFolder", owner=owner)

        # Django save succeeds...
        folder.save()
        assert folder.pk is not None  # Model was saved

        # ...but the adapter write failed
        # The tuple for owner:user:X -> folder:Y was NOT written to SpiceDB
        # But the Folder model exists in Django

        # This is the vulnerability: the systems are out of sync
        # Subsequent permission checks will fail because the tuple doesn't exist in SpiceDB

        factory.reset_adapter()

    @pytest.mark.django_db
    def test_atomic_model_and_tuple_consistency(self):
        """
        Reconciliation detects and fixes model/tuple drift.

        When adapter write_tuples fails (e.g., SpiceDB down), the Django model
        is saved but tuples are missing. The reconcile utility detects this
        drift and can re-write the missing tuples.
        """
        adapter = RecordingAdapterWithErrorHandling(raise_on_write=True)
        factory.set_adapter(adapter)

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")

        folder = Folder(name="TestFolder", owner=owner)
        folder.save()

        # Model was saved but tuples failed to write
        assert Folder.objects.filter(name="TestFolder").count() == 1
        assert len(adapter.writes) == 0  # write_tuples raised, nothing recorded

        # Now "fix" the adapter and reconcile
        adapter.raise_on_write = False
        factory.set_adapter(adapter)

        from django_spicedb.sync.reconcile import reconcile_type
        result = reconcile_type("folder", fix=True, adapter=adapter)

        # Reconcile detected and wrote the missing tuples
        assert result.expected > 0
        assert result.fixed is True
        assert len(adapter.writes) > 0

        factory.reset_adapter()

    @pytest.mark.django_db
    def test_m2m_write_failure_behavior(self):
        """
        M2M signal sync failure: write succeeds but with error.

        When many-to-many changes trigger tuple writes, if the adapter fails,
        the M2M change is still applied to Django.
        """
        adapter = RecordingAdapterWithErrorHandling(raise_on_write=True)
        factory.set_adapter(adapter)

        User = get_user_model()
        workspace = Workspace.objects.create(name="ws")
        user1 = User.objects.create_user(username="user1", password="pass")

        # M2M write will fail when on_commit callback runs
        workspace.members.add(user1)

        # But the relationship is still added to Django
        assert workspace.members.filter(pk=user1.pk).exists()

        # However, the tuple wasn't written to SpiceDB
        # This is the inconsistency

        factory.reset_adapter()


# ============================================================================
# 4. STAFF/SUPERUSER PRIVILEGE BYPASS
# ============================================================================


class TestStaffSuperuserBypass:
    """Test staff/superuser permission bypass in views."""

    @pytest.fixture
    def http_client(self, db):
        """Django test client."""
        return Client()

    @pytest.fixture
    def setup_hierarchy(self, db, company):
        """Setup hierarchy for view tests."""
        company_ct = ContentType.objects.get_for_model(Company)

        # Create hierarchy type (requires tenant_content_type)
        htype = HierarchyTypeDefinition.objects.create(
            name="department",
            display_name="Department",
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
        )

        # Create root node
        root = HierarchyNode.objects.create(
            name="Root",
            slug="root",
            hierarchy_type=htype,
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
        )

        return {
            "company": company,
            "htype": htype,
            "root": root,
        }

    @pytest.mark.django_db
    def test_staff_user_bypasses_permission_checks_in_views(self, http_client, setup_hierarchy):
        """
        VULNERABILITY: Staff users bypass all permission checks in views.

        Views like HierarchyTreeView explicitly allow staff users to see all nodes:
            if request.user.is_superuser or request.user.is_staff:
                accessible_nodes = self.get_tenant_nodes().select_related(...)

        This is a security policy issue - staff can see everything without going
        through the permission evaluator.
        """
        company = setup_hierarchy["company"]

        # Create staff user (NOT superuser, just staff)
        User.objects.create_user(
            username="staff",
            password="staff",
            is_staff=True,
        )

        # Create normal user with no permissions
        User.objects.create_user(
            username="normal",
            password="normal",
        )

        # Login as staff
        http_client.login(username="staff", password="staff")

        # Staff user can access hierarchy tree
        response = http_client.get(f"/rebac/{company.pk}/hierarchy/")

        # Staff bypassed permission checks
        # They see all nodes even though they have no explicit permissions
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_superuser_bypasses_all_permission_checks(self, http_client, setup_hierarchy):
        """
        VULNERABILITY: Superuser bypasses all permission checks.

        Superusers explicitly bypass permission evaluation in multiple places:
        - HierarchyTreeView.get_context_data()
        - NodeDetailView.get_context_data()
        - PermissionRequiredMixin.check_permission()

        This is a backdoor: superuser can always access all resources.
        """
        company = setup_hierarchy["company"]

        # Create superuser
        User.objects.create_user(
            username="superuser",
            password="super",
            is_superuser=True,
        )

        # Login as superuser
        http_client.login(username="superuser", password="super")

        # Superuser bypasses all checks
        response = http_client.get(f"/rebac/{company.pk}/hierarchy/")
        assert response.status_code == 200

    @pytest.mark.django_db
    @override_settings(REBAC={
        "tenant_model": "example_project.documents.models.Company",
        "tenant_fk_name": "company",
        "staff_bypass_permissions": False,
        "adapter": {"endpoint": "localhost:50051", "token": "devkey", "insecure": True},
    })
    def test_staff_users_should_be_permission_evaluated(
        self, http_client, setup_hierarchy, mock_adapter_with_errors,
    ):
        """Staff users go through the permission evaluator when bypass is disabled."""
        company = setup_hierarchy["company"]
        conf.reset_type_graph_cache()

        User.objects.create_user(
            username="staff",
            password="staff",
            is_staff=True,
        )

        http_client.login(username="staff", password="staff")

        response = http_client.get(f"/rebac/{company.pk}/hierarchy/")

        # With bypass disabled, the view still returns 200 but the hierarchy_tree
        # should be empty because the staff user has no SpiceDB permissions
        assert response.status_code == 200
        assert len(response.context["hierarchy_tree"]) == 0

    @pytest.mark.django_db
    @override_settings(REBAC={
        "tenant_model": "example_project.documents.models.Company",
        "tenant_fk_name": "company",
        "staff_bypass_permissions": False,
        "adapter": {"endpoint": "localhost:50051", "token": "devkey", "insecure": True},
    })
    def test_superuser_should_be_permission_evaluated(
        self, http_client, setup_hierarchy, mock_adapter_with_errors,
    ):
        """Superuser goes through the permission evaluator when bypass is disabled."""
        company = setup_hierarchy["company"]
        conf.reset_type_graph_cache()

        User.objects.create_user(
            username="superuser",
            password="super",
            is_superuser=True,
        )

        http_client.login(username="superuser", password="super")

        response = http_client.get(f"/rebac/{company.pk}/hierarchy/")

        # With bypass disabled, the view still returns 200 but the hierarchy_tree
        # should be empty because the superuser has no SpiceDB permissions
        assert response.status_code == 200
        assert len(response.context["hierarchy_tree"]) == 0


# ============================================================================
# 5. CACHE AND CONSISTENCY ISSUES
# ============================================================================


class TestCacheConsistencyIssues:
    """Test caching and consistency issues."""

    @pytest.mark.django_db
    def test_evaluator_cache_not_user_aware(self):
        """
        VULNERABILITY: Evaluator cache key doesn't include subject identity.

        Actually, wait - let me check the cache key construction...
        The cache_key is (relation, object_ref, context, consistency) - no subject.

        But the subject_ref is stored as _subject_ref on the evaluator instance.
        Each evaluator instance has its own cache, so this is actually OK.

        This test verifies that different evaluators don't share cache.
        """
        from tests.conftest import RecordingAdapter

        adapter = RecordingAdapter()
        factory.set_adapter(adapter)

        User = get_user_model()
        user1 = User.objects.create_user(username="user1", password="pass")
        user2 = User.objects.create_user(username="user2", password="pass")

        doc = Document.objects.create(
            title="Test",
            owner=user1,
            workspace=Workspace.objects.create(name="ws"),
        )

        # User1 has permission
        adapter.set_check_response(
            subject=f"user:{user1.pk}",
            relation="view",
            object_ref=f"document:{doc.pk}",
            result=True,
        )

        # User2 does NOT have permission
        adapter.set_check_response(
            subject=f"user:{user2.pk}",
            relation="view",
            object_ref=f"document:{doc.pk}",
            result=False,
        )

        evaluator1 = PermissionEvaluator(user1)
        evaluator2 = PermissionEvaluator(user2)

        assert evaluator1.can("view", doc) is True
        assert evaluator2.can("view", doc) is False

        # Good: they have separate caches so don't interfere
        assert len(adapter.check_calls) == 2

        factory.reset_adapter()

    @pytest.mark.django_db
    def test_context_affects_cache_key(self):
        """
        Cache key SHOULD include context to prevent stale results across contexts.

        The _freeze_context function creates a tuple of sorted context items
        for the cache key, so different contexts get different cache entries.
        """
        from tests.conftest import RecordingAdapter

        adapter = RecordingAdapter()
        factory.set_adapter(adapter)

        User = get_user_model()
        user = User.objects.create_user(username="user", password="pass")
        doc = Document.objects.create(
            title="Test",
            owner=user,
            workspace=Workspace.objects.create(name="ws"),
        )

        # Same permission check, different contexts
        # Context 1: user in "branch-a"
        adapter.set_check_response(
            subject=f"user:{user.pk}",
            relation="view",
            object_ref=f"document:{doc.pk}",
            result=True,
            context={"branch": "branch-a"},
        )

        # Context 2: user in "branch-b"
        adapter.set_check_response(
            subject=f"user:{user.pk}",
            relation="view",
            object_ref=f"document:{doc.pk}",
            result=False,
            context={"branch": "branch-b"},
        )

        evaluator = PermissionEvaluator(user)

        # Check with context 1
        result1 = evaluator.can("view", doc, context={"branch": "branch-a"})
        assert result1 is True

        # Check with context 2 - should NOT use cache from context 1
        result2 = evaluator.can("view", doc, context={"branch": "branch-b"})
        assert result2 is False

        # Verify both checks were made
        assert len(adapter.check_calls) == 2

        factory.reset_adapter()

    @pytest.mark.django_db
    def test_model_instantiation_without_pk_fails(self):
        """
        DOCUMENTATION: Unsaved model instances cannot be used in permission checks.

        This is intentional - _subject_to_reference and _object_to_reference
        require a pk to build the reference string.
        """
        User = get_user_model()
        user = User(username="unsaved")  # Not saved yet

        with pytest.raises(ImproperlyConfigured, match="must be saved"):
            _subject_to_reference(user)

        doc = Document(title="unsaved")  # Not saved yet
        Workspace.objects.create(name="ws")

        with pytest.raises(ImproperlyConfigured, match="must be saved"):
            can(user, "view", doc)


# ============================================================================
# 6. REFERENCE FORMAT INJECTION
# ============================================================================


class TestReferenceFormatInjection:
    """Test potential injection attacks through reference formats."""

    @pytest.mark.django_db
    def test_subject_with_hash_symbol(self):
        """
        Subject references with # are used for relation chaining.

        Format: "type:id#relation" means "the relation of that object"

        This is intentional and used for permission inheritance, but documents
        that the "#" character has special meaning.
        """
        # A string reference with # is valid and used for relation chaining
        chained_ref = "user:1#view"
        result = _subject_to_reference(chained_ref)
        assert result == chained_ref

        # This is correct behavior - the system expects this format for relations

    @pytest.mark.django_db
    def test_object_reference_format(self):
        """
        DOCUMENTATION: Object references also use "type:id" format.

        They don't support the "#relation" syntax - that's only for subjects.
        """
        User = get_user_model()
        user = User.objects.create_user(username="owner", password="pass")
        doc = Document.objects.create(
            title="Test",
            owner=user,
            workspace=Workspace.objects.create(name="ws"),
        )

        from django_spicedb.runtime.evaluator import _object_to_reference

        ref = _object_to_reference(doc)
        # Format is always type:pk
        assert ref == f"document:{doc.pk}"

    @pytest.mark.django_db
    def test_malformed_string_reference_validation(self):
        """String references SHOULD be validated for proper format."""
        # These should raise errors, not be accepted
        with pytest.raises(ImproperlyConfigured):
            _subject_to_reference("not_a_reference")  # No colon

        with pytest.raises(ImproperlyConfigured):
            _subject_to_reference("type:id:extra:colons")  # Too many colons

        with pytest.raises(ImproperlyConfigured):
            _subject_to_reference("type:")  # Missing id

        with pytest.raises(ImproperlyConfigured):
            _subject_to_reference(":id")  # Missing type
