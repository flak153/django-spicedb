"""
TDD tests for multi-tenant hierarchy system.

These tests define the expected UX for:
1. Tenant configuration helpers
2. Hierarchy tuple sync to SpiceDB
3. Tenant-aware permission evaluation
4. Cross-tenant isolation
5. accessible_by() for hierarchy nodes
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.models import HierarchyNode, HierarchyNodeRole, HierarchyTypeDefinition
from django_rebac.sync import registry
from django_rebac.hierarchy.signals import connect_hierarchy_signals, disconnect_hierarchy_signals

from example_project.documents.models import Company


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tenant_settings():
    """Settings with tenant model configured."""
    return {
        "tenant_model": "example_project.documents.models.Company",
        "tenant_fk_name": "company",
        "types": {
            "user": {"model": "django.contrib.auth.models.User"},
            "hierarchy_node": {
                "model": "django_rebac.models.HierarchyNode",
                "relations": {
                    "parent": "hierarchy_node",
                    "manager": "user",
                    "viewer": "user",
                },
                "permissions": {
                    "manage": "manager + parent->manage",
                    "view": "viewer + manage + parent->view",
                },
            },
        },
        "db_overrides": False,
    }


@pytest.fixture
def company(db):
    """Test tenant."""
    return Company.objects.create(name="Acme Corp", slug="acme")


@pytest.fixture
def other_company(db):
    """Another tenant for isolation tests."""
    return Company.objects.create(name="Other Corp", slug="other")


@pytest.fixture
def company_ct(db):
    """ContentType for Company."""
    return ContentType.objects.get_for_model(Company)


@pytest.fixture
def user(db):
    """Test user."""
    User = get_user_model()
    return User.objects.create_user(username="alice", password="pass")


@pytest.fixture
def other_user(db):
    """Another test user."""
    User = get_user_model()
    return User.objects.create_user(username="bob", password="pass")


@pytest.fixture
def region_type(company, company_ct):
    """Region hierarchy type."""
    return HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="region",
        display_name="Region",
        slug="region",
        level=0,
    )


@pytest.fixture
def branch_type(company, company_ct, region_type):
    """Branch hierarchy type under Region."""
    return HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="branch",
        display_name="Branch",
        slug="branch",
        level=1,
        parent_type=region_type,
    )


# =============================================================================
# 1. Tenant Configuration Tests
# =============================================================================


class TestTenantConfiguration:
    """Tests for tenant configuration helpers.

    Expected UX:
    - Configure tenant model in settings: REBAC['tenant_model'] = 'myapp.Company'
    - Helper functions to get tenant model and content type
    """

    @pytest.mark.django_db
    def test_get_tenant_model_returns_model_class(self, tenant_settings):
        """get_tenant_model() returns the configured tenant model class."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            from django_rebac.conf import get_tenant_model

            tenant_model = get_tenant_model()
            assert tenant_model is Company

    @pytest.mark.django_db
    def test_get_tenant_model_raises_if_not_configured(self):
        """get_tenant_model() raises if tenant_model not in settings."""
        settings_without_tenant = {
            "types": {"user": {"model": "django.contrib.auth.models.User"}},
        }
        with override_settings(REBAC=settings_without_tenant):
            conf.reset_type_graph_cache()

            from django_rebac.conf import get_tenant_model

            with pytest.raises(ValueError, match="tenant_model"):
                get_tenant_model()

    @pytest.mark.django_db
    def test_get_tenant_content_type(self, tenant_settings):
        """get_tenant_content_type() returns ContentType for tenant model."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            from django_rebac.conf import get_tenant_content_type

            ct = get_tenant_content_type()
            assert ct.model_class() is Company

    @pytest.mark.django_db
    def test_get_tenant_fk_name(self, tenant_settings):
        """get_tenant_fk_name() returns the configured FK name."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            from django_rebac.conf import get_tenant_fk_name

            assert get_tenant_fk_name() == "company"

    @pytest.mark.django_db
    def test_get_tenant_fk_name_default(self, tenant_settings):
        """get_tenant_fk_name() defaults to 'tenant' if not configured."""
        settings_without_fk_name = {**tenant_settings}
        del settings_without_fk_name["tenant_fk_name"]

        with override_settings(REBAC=settings_without_fk_name):
            conf.reset_type_graph_cache()

            from django_rebac.conf import get_tenant_fk_name

            assert get_tenant_fk_name() == "tenant"


# =============================================================================
# 2. Hierarchy Tuple Sync Tests
# =============================================================================


class TestHierarchyTupleSync:
    """Tests for automatic tuple sync when hierarchy models change.

    Expected UX:
    - Creating HierarchyNode with parent auto-writes parent tuple
    - Creating HierarchyNodeRole auto-writes role tuple
    - Deleting cleans up tuples
    """

    @pytest.fixture(autouse=True)
    def setup_hierarchy_signals(self):
        """Connect hierarchy signals for each test."""
        connect_hierarchy_signals()
        yield
        disconnect_hierarchy_signals()

    @pytest.mark.django_db
    def test_hierarchy_node_parent_tuple_on_create(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, branch_type
    ):
        """Creating a HierarchyNode with parent writes parent tuple to SpiceDB."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            registry.refresh()

            # Create root node
            root = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North Region",
            )

            # Create child node
            child = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=branch_type,
                name="Downtown Branch",
                parent=root,
            )

            # Should have written parent tuple
            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }

            assert (
                f"hierarchy_node:{child.pk}",
                "parent",
                f"hierarchy_node:{root.pk}",
            ) in write_tuples

    @pytest.mark.django_db
    def test_hierarchy_node_role_tuple_on_create(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, user
    ):
        """Creating a HierarchyNodeRole writes role tuple to SpiceDB."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            registry.refresh()

            node = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North Region",
            )

            # Assign manager role
            HierarchyNodeRole.objects.create(
                node=node,
                user=user,
                role=HierarchyNodeRole.ROLE_MANAGER,
            )

            # Should have written role tuple
            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }

            assert (
                f"hierarchy_node:{node.pk}",
                "manager",
                f"user:{user.pk}",
            ) in write_tuples

    @pytest.mark.django_db
    def test_hierarchy_node_role_tuple_on_delete(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, user
    ):
        """Deleting a HierarchyNodeRole deletes tuple from SpiceDB."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            registry.refresh()

            node = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North Region",
            )

            role = HierarchyNodeRole.objects.create(
                node=node,
                user=user,
                role=HierarchyNodeRole.ROLE_MANAGER,
            )

            # Clear writes, then delete
            recording_adapter.writes.clear()
            role.delete()

            # Should have deleted role tuple
            delete_tuples = {
                (d.object, d.relation, d.subject)
                for d in recording_adapter.deletes
            }

            assert (
                f"hierarchy_node:{node.pk}",
                "manager",
                f"user:{user.pk}",
            ) in delete_tuples

    @pytest.mark.django_db
    def test_hierarchy_node_parent_tuple_on_delete(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, branch_type
    ):
        """Deleting a HierarchyNode with parent deletes parent tuple."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            registry.refresh()

            root = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North Region",
            )

            child = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=branch_type,
                name="Downtown Branch",
                parent=root,
            )

            child_pk = child.pk
            root_pk = root.pk

            # Clear, then delete child
            recording_adapter.deletes.clear()
            child.delete()

            delete_tuples = {
                (d.object, d.relation, d.subject)
                for d in recording_adapter.deletes
            }

            assert (
                f"hierarchy_node:{child_pk}",
                "parent",
                f"hierarchy_node:{root_pk}",
            ) in delete_tuples


# =============================================================================
# 3. Tenant-Aware Permission Evaluation Tests
# =============================================================================


class TestTenantAwarePermissionEvaluation:
    """Tests for tenant-aware permission checks.

    Expected UX:
    - TenantAwarePermissionEvaluator checks tenant isolation BEFORE SpiceDB
    - Cross-tenant access is automatically denied
    - Same-tenant access defers to SpiceDB
    """

    @pytest.mark.django_db
    def test_cross_tenant_access_denied(
        self, tenant_settings, recording_adapter, company, other_company, company_ct, region_type, user
    ):
        """Accessing a node from another tenant is automatically denied."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # Node belongs to company
            node = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North Region",
            )

            # Even if SpiceDB would allow, cross-tenant should deny
            recording_adapter.set_check_response(
                subject=f"user:{user.pk}",
                relation="view",
                object_ref=f"hierarchy_node:{node.pk}",
                result=True,  # SpiceDB says yes
            )

            from django_rebac.tenant import TenantAwarePermissionEvaluator

            # User trying to access from other_company context
            evaluator = TenantAwarePermissionEvaluator(user, tenant=other_company)

            # Should be denied - node.tenant != evaluator.tenant
            assert evaluator.can("view", node) is False

            # Should NOT have called SpiceDB (short-circuit)
            assert len(recording_adapter.check_calls) == 0

    @pytest.mark.django_db
    def test_same_tenant_defers_to_spicedb(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, user
    ):
        """Same-tenant access defers to SpiceDB for permission check."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            node = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North Region",
            )

            recording_adapter.set_check_response(
                subject=f"user:{user.pk}",
                relation="view",
                object_ref=f"hierarchy_node:{node.pk}",
                result=True,
            )

            from django_rebac.tenant import TenantAwarePermissionEvaluator

            evaluator = TenantAwarePermissionEvaluator(user, tenant=company)

            assert evaluator.can("view", node) is True
            assert len(recording_adapter.check_calls) == 1

    @pytest.mark.django_db
    def test_evaluator_inherits_from_base(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, user
    ):
        """TenantAwarePermissionEvaluator has same API as PermissionEvaluator."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            from django_rebac.tenant import TenantAwarePermissionEvaluator
            from django_rebac.runtime import PermissionEvaluator

            evaluator = TenantAwarePermissionEvaluator(user, tenant=company)

            # Should have all the base methods
            assert hasattr(evaluator, "can")
            assert hasattr(evaluator, "filter_accessible")
            assert isinstance(evaluator, PermissionEvaluator)


# =============================================================================
# 4. Tenant Context Tests
# =============================================================================


class TestTenantContext:
    """Tests for tenant context management.

    Expected UX:
    - Thread-local tenant context
    - Context manager for scoped tenant
    - Middleware sets tenant from request
    """

    @pytest.mark.django_db
    def test_set_and_get_current_tenant(self, company):
        """Can set and get current tenant via thread-local."""
        from django_rebac.tenant import get_current_tenant, set_current_tenant, clear_current_tenant

        # Initially None
        assert get_current_tenant() is None

        set_current_tenant(company)
        assert get_current_tenant() == company

        clear_current_tenant()
        assert get_current_tenant() is None

    @pytest.mark.django_db
    def test_tenant_context_manager(self, company, other_company):
        """Context manager scopes tenant and restores previous."""
        from django_rebac.tenant import get_current_tenant, tenant_context, set_current_tenant

        set_current_tenant(company)

        with tenant_context(other_company):
            assert get_current_tenant() == other_company

        # Restored after exit
        assert get_current_tenant() == company

    @pytest.mark.django_db
    def test_tenant_context_manager_clears_on_exit(self, company):
        """Context manager clears tenant if none was set before."""
        from django_rebac.tenant import get_current_tenant, tenant_context, clear_current_tenant

        clear_current_tenant()

        with tenant_context(company):
            assert get_current_tenant() == company

        assert get_current_tenant() is None


# =============================================================================
# 5. Accessible By Tests
# =============================================================================


class TestHierarchyAccessibleBy:
    """Tests for querying accessible hierarchy nodes.

    Expected UX:
    - HierarchyNode.objects.accessible_by(user, 'view') returns viewable nodes
    - Automatically filters by current tenant context
    - Uses LookupResources for efficient batch lookup
    """

    @pytest.mark.django_db
    def test_accessible_by_returns_permitted_nodes(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, user
    ):
        """accessible_by() returns nodes the user can access."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            node1 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North Region",
            )
            node2 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="South Region",
            )
            HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="West Region",  # Not accessible
            )

            # Mock SpiceDB response - user can view node1 and node2
            recording_adapter.set_lookup_response(
                subject=f"user:{user.pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=[str(node1.pk), str(node2.pk)],
            )

            from django_rebac.tenant import tenant_context

            with tenant_context(company):
                qs = HierarchyNode.objects.accessible_by(user, "view")
                names = set(qs.values_list("name", flat=True))

            assert names == {"North Region", "South Region"}

    @pytest.mark.django_db
    def test_accessible_by_filters_by_tenant(
        self, tenant_settings, recording_adapter, company, other_company, company_ct, region_type, user
    ):
        """accessible_by() only returns nodes from current tenant."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # Node in company
            node1 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="Acme North",
            )

            # Create type for other company
            other_region_type = HierarchyTypeDefinition.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(other_company.pk),
                name="region",
                display_name="Region",
                slug="region",
                level=0,
            )

            # Node in other_company
            node2 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(other_company.pk),
                hierarchy_type=other_region_type,
                name="Other North",
            )

            # SpiceDB says user can view both
            recording_adapter.set_lookup_response(
                subject=f"user:{user.pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=[str(node1.pk), str(node2.pk)],
            )

            from django_rebac.tenant import tenant_context

            # Query in company context - should only see company's node
            with tenant_context(company):
                qs = HierarchyNode.objects.accessible_by(user, "view")
                names = set(qs.values_list("name", flat=True))

            assert names == {"Acme North"}
            assert "Other North" not in names


# =============================================================================
# 6. Hierarchy Lookup Helper Tests
# =============================================================================


class TestHierarchyLookupHelper:
    """Tests for efficient hierarchy permission lookups.

    Expected UX:
    - TenantHierarchyLookup caches accessible node IDs per request
    - Single LookupResources call, then filter by FK
    """

    @pytest.mark.django_db
    def test_get_accessible_hierarchy_nodes(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, user
    ):
        """get_accessible_hierarchy_nodes returns set of accessible node IDs."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            node1 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North",
            )
            node2 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="South",
            )

            recording_adapter.set_lookup_response(
                subject=f"user:{user.pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=[str(node1.pk), str(node2.pk)],
            )

            from django_rebac.tenant import TenantHierarchyLookup

            lookup = TenantHierarchyLookup(user, company)
            accessible_ids = lookup.get_accessible_hierarchy_nodes("view")

            assert accessible_ids == {node1.pk, node2.pk}

    @pytest.mark.django_db
    def test_lookup_caches_results(
        self, tenant_settings, recording_adapter, company, company_ct, region_type, user
    ):
        """Multiple calls to get_accessible_hierarchy_nodes use cache."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            node1 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="North",
            )

            recording_adapter.set_lookup_response(
                subject=f"user:{user.pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=[str(node1.pk)],
            )

            from django_rebac.tenant import TenantHierarchyLookup

            lookup = TenantHierarchyLookup(user, company)

            # First call
            lookup.get_accessible_hierarchy_nodes("view")
            assert len(recording_adapter.lookup_calls) == 1

            # Second call - should use cache
            lookup.get_accessible_hierarchy_nodes("view")
            assert len(recording_adapter.lookup_calls) == 1  # Still 1
