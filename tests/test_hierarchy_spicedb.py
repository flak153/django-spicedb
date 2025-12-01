"""
Real SpiceDB integration tests for multi-tenant hierarchy.

These tests require Docker and SpiceDB running. They verify:
1. Schema publishing with hierarchy_node type
2. Tuple sync for parent relationships and role assignments
3. Permission inheritance through parent->permission arrows
4. 4-level hierarchy permission checks
5. LookupResources for accessible nodes
6. Cross-tenant isolation at SpiceDB level

Run with: poetry run pytest tests/test_hierarchy_spicedb.py -v
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.adapters import factory
from django_rebac.adapters.base import TupleKey, TupleWrite
from django_rebac.hierarchy.signals import connect_hierarchy_signals, disconnect_hierarchy_signals
from django_rebac.models import HierarchyNode, HierarchyNodeRole, HierarchyTypeDefinition
from django_rebac.runtime import PermissionEvaluator
from django_rebac.schema import publish_schema
from django_rebac.sync import registry
from django_rebac.tenant import TenantAwarePermissionEvaluator, tenant_context

from example_project.documents.models import Company


# =============================================================================
# Test Configuration
# =============================================================================


def _hierarchy_config():
    """REBAC configuration for hierarchy tests.

    Includes hierarchy_resource and document types to maintain compatibility
    with existing SpiceDB tuples from other tests.
    """
    return {
        "tenant_model": "example_project.documents.models.Company",
        "tenant_fk_name": "company",
        "types": {
            "user": {"model": "django.contrib.auth.models.User"},
            # Existing types to avoid schema conflicts
            "hierarchy_resource": {
                "relations": {
                    "parent": "hierarchy_resource",
                    "manager": "user",
                },
                "permissions": {
                    "manage": "manager + parent->manage",
                },
            },
            "document": {
                "relations": {
                    "owner": "user",
                    "parent": "hierarchy_resource",
                },
                "permissions": {"view": "owner"},
            },
            # New hierarchy_node type
            "hierarchy_node": {
                "model": "django_rebac.models.HierarchyNode",
                "relations": {
                    "parent": "hierarchy_node",
                    "owner": "user",
                    "manager": "user",
                    "viewer": "user",
                    "lead": "user",
                    "member": "user",
                },
                "permissions": {
                    "admin": "owner + parent->admin",
                    "manage": "manager + lead + admin + parent->manage",
                    "view": "viewer + member + manage + parent->view",
                },
            },
        },
        "db_overrides": False,
    }


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def hierarchy_schema(spicedb_adapter):
    """Publish hierarchy schema to SpiceDB."""
    config = _hierarchy_config()
    with override_settings(REBAC=config):
        conf.reset_type_graph_cache()
        graph = conf.get_type_graph()
        publish_schema(spicedb_adapter, graph=graph)
        yield spicedb_adapter
    conf.reset_type_graph_cache()


@pytest.fixture
def configured_adapter(spicedb_adapter, hierarchy_schema):
    """Set adapter and connect signals."""
    # Clean up any leftover tuples from previous tests BEFORE running the test
    # This ensures test isolation even if previous test runs left stale data
    spicedb_adapter.delete_all_relationships("hierarchy_node")

    factory.set_adapter(spicedb_adapter)
    connect_hierarchy_signals()
    yield spicedb_adapter
    disconnect_hierarchy_signals()
    factory.reset_adapter()


@pytest.fixture
def company(db):
    """Test tenant."""
    return Company.objects.create(
        name=f"Acme-{uuid.uuid4().hex[:8]}",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
    )


@pytest.fixture
def other_company(db):
    """Another tenant for isolation tests."""
    return Company.objects.create(
        name=f"Other-{uuid.uuid4().hex[:8]}",
        slug=f"other-{uuid.uuid4().hex[:8]}",
    )


@pytest.fixture
def company_ct(db):
    """ContentType for Company."""
    return ContentType.objects.get_for_model(Company)


@pytest.fixture
def users(db):
    """Create test users with unique usernames."""
    User = get_user_model()
    suffix = uuid.uuid4().hex[:8]
    return {
        "ceo": User.objects.create_user(username=f"ceo-{suffix}", password="pass"),
        "regional_mgr": User.objects.create_user(username=f"regional-{suffix}", password="pass"),
        "branch_mgr": User.objects.create_user(username=f"branch-{suffix}", password="pass"),
        "dept_head": User.objects.create_user(username=f"dept-{suffix}", password="pass"),
        "team_lead": User.objects.create_user(username=f"lead-{suffix}", password="pass"),
        "employee": User.objects.create_user(username=f"emp-{suffix}", password="pass"),
        "outsider": User.objects.create_user(username=f"outsider-{suffix}", password="pass"),
    }


@pytest.fixture
def hierarchy_types(company, company_ct):
    """Create 4-level hierarchy type definitions."""
    region = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="region",
        display_name="Region",
        slug=f"region-{uuid.uuid4().hex[:8]}",
        level=0,
    )
    branch = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="branch",
        display_name="Branch",
        slug=f"branch-{uuid.uuid4().hex[:8]}",
        level=1,
        parent_type=region,
    )
    department = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="department",
        display_name="Department",
        slug=f"dept-{uuid.uuid4().hex[:8]}",
        level=2,
        parent_type=branch,
    )
    team = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="team",
        display_name="Team",
        slug=f"team-{uuid.uuid4().hex[:8]}",
        level=3,
        parent_type=department,
    )
    return {"region": region, "branch": branch, "department": department, "team": team}


# =============================================================================
# Schema Tests
# =============================================================================


class TestSchemaPublishing:
    """Tests for SpiceDB schema with hierarchy_node type."""

    def test_schema_compiles_and_publishes(self, spicedb_adapter):
        """Schema with hierarchy_node publishes successfully."""
        config = _hierarchy_config()
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            graph = conf.get_type_graph()
            schema = graph.compile_schema()

            # Verify schema content
            assert "definition hierarchy_node" in schema
            assert "relation parent: hierarchy_node" in schema
            assert "relation manager: user" in schema
            assert "permission manage =" in schema
            assert "parent->manage" in schema

            # Publish should not raise
            zedtoken = publish_schema(spicedb_adapter, graph=graph)
            assert zedtoken is not None


# =============================================================================
# Basic Tuple Operations
# =============================================================================


class TestTupleOperations:
    """Tests for writing and deleting tuples."""

    def test_write_parent_tuple(self, hierarchy_schema):
        """Can write parent relationship tuple."""
        adapter = hierarchy_schema
        parent_id = uuid.uuid4().hex
        child_id = uuid.uuid4().hex

        key = TupleKey(
            object=f"hierarchy_node:{child_id}",
            relation="parent",
            subject=f"hierarchy_node:{parent_id}",
        )
        adapter.write_tuples([TupleWrite(key=key)])

        # Verify via check - child should inherit parent's permissions
        # But we need a user with permission on parent first
        user_id = uuid.uuid4().hex
        adapter.write_tuples([
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{parent_id}",
                relation="manager",
                subject=f"user:{user_id}",
            ))
        ])

        # User should be able to manage child via parent->manage
        assert adapter.check(
            subject=f"user:{user_id}",
            relation="manage",
            object_=f"hierarchy_node:{child_id}",
            consistency="fully_consistent",
        )

    def test_write_role_tuple(self, hierarchy_schema):
        """Can write role assignment tuple."""
        adapter = hierarchy_schema
        node_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex

        key = TupleKey(
            object=f"hierarchy_node:{node_id}",
            relation="viewer",
            subject=f"user:{user_id}",
        )
        adapter.write_tuples([TupleWrite(key=key)])

        assert adapter.check(
            subject=f"user:{user_id}",
            relation="view",
            object_=f"hierarchy_node:{node_id}",
            consistency="fully_consistent",
        )

    def test_delete_tuple_revokes_permission(self, hierarchy_schema):
        """Deleting tuple revokes permission."""
        adapter = hierarchy_schema
        node_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex

        key = TupleKey(
            object=f"hierarchy_node:{node_id}",
            relation="manager",
            subject=f"user:{user_id}",
        )

        # Write then verify
        adapter.write_tuples([TupleWrite(key=key)])
        assert adapter.check(
            subject=f"user:{user_id}",
            relation="manage",
            object_=f"hierarchy_node:{node_id}",
            consistency="fully_consistent",
        )

        # Delete then verify revoked
        adapter.delete_tuples([key])
        assert not adapter.check(
            subject=f"user:{user_id}",
            relation="manage",
            object_=f"hierarchy_node:{node_id}",
            consistency="fully_consistent",
        )


# =============================================================================
# Permission Inheritance Tests
# =============================================================================


class TestPermissionInheritance:
    """Tests for permission inheritance through parent relationship."""

    def test_two_level_inheritance(self, hierarchy_schema):
        """Manager of parent can manage child."""
        adapter = hierarchy_schema
        parent_id = uuid.uuid4().hex
        child_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex

        # Create parent -> child relationship
        adapter.write_tuples([
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{child_id}",
                relation="parent",
                subject=f"hierarchy_node:{parent_id}",
            )),
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{parent_id}",
                relation="manager",
                subject=f"user:{user_id}",
            )),
        ])

        # Direct permission on parent
        assert adapter.check(
            subject=f"user:{user_id}",
            relation="manage",
            object_=f"hierarchy_node:{parent_id}",
            consistency="fully_consistent",
        )

        # Inherited permission on child
        assert adapter.check(
            subject=f"user:{user_id}",
            relation="manage",
            object_=f"hierarchy_node:{child_id}",
            consistency="fully_consistent",
        )

    def test_four_level_inheritance(self, hierarchy_schema):
        """Admin at level 0 can manage all descendants."""
        adapter = hierarchy_schema

        # Create 4-level chain: region -> branch -> dept -> team
        region_id = uuid.uuid4().hex
        branch_id = uuid.uuid4().hex
        dept_id = uuid.uuid4().hex
        team_id = uuid.uuid4().hex
        admin_id = uuid.uuid4().hex

        adapter.write_tuples([
            # Hierarchy
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{branch_id}",
                relation="parent",
                subject=f"hierarchy_node:{region_id}",
            )),
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{dept_id}",
                relation="parent",
                subject=f"hierarchy_node:{branch_id}",
            )),
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{team_id}",
                relation="parent",
                subject=f"hierarchy_node:{dept_id}",
            )),
            # Owner (admin) at region level
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{region_id}",
                relation="owner",
                subject=f"user:{admin_id}",
            )),
        ])

        # Admin can manage all levels
        for node_id in [region_id, branch_id, dept_id, team_id]:
            assert adapter.check(
                subject=f"user:{admin_id}",
                relation="manage",
                object_=f"hierarchy_node:{node_id}",
                consistency="fully_consistent",
            ), f"Admin should manage {node_id}"

            assert adapter.check(
                subject=f"user:{admin_id}",
                relation="view",
                object_=f"hierarchy_node:{node_id}",
                consistency="fully_consistent",
            ), f"Admin should view {node_id}"

    def test_no_upward_inheritance(self, hierarchy_schema):
        """Manager of child cannot manage parent."""
        adapter = hierarchy_schema
        parent_id = uuid.uuid4().hex
        child_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex

        adapter.write_tuples([
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{child_id}",
                relation="parent",
                subject=f"hierarchy_node:{parent_id}",
            )),
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{child_id}",
                relation="manager",
                subject=f"user:{user_id}",
            )),
        ])

        # Can manage child
        assert adapter.check(
            subject=f"user:{user_id}",
            relation="manage",
            object_=f"hierarchy_node:{child_id}",
            consistency="fully_consistent",
        )

        # Cannot manage parent
        assert not adapter.check(
            subject=f"user:{user_id}",
            relation="manage",
            object_=f"hierarchy_node:{parent_id}",
            consistency="fully_consistent",
        )


# =============================================================================
# LookupResources Tests
# =============================================================================


class TestLookupResources:
    """Tests for reverse lookups - finding all accessible resources."""

    def test_lookup_returns_accessible_nodes(self, hierarchy_schema):
        """LookupResources returns all nodes user can access."""
        adapter = hierarchy_schema
        user_id = uuid.uuid4().hex

        # Create 3 nodes, user is manager of 2
        node1 = uuid.uuid4().hex
        node2 = uuid.uuid4().hex
        node3 = uuid.uuid4().hex

        adapter.write_tuples([
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{node1}",
                relation="manager",
                subject=f"user:{user_id}",
            )),
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{node2}",
                relation="viewer",
                subject=f"user:{user_id}",
            )),
            # node3 has no assignment
        ])

        # Lookup viewable nodes
        viewable = set(adapter.lookup_resources(
            subject=f"user:{user_id}",
            relation="view",
            resource_type="hierarchy_node",
            consistency="fully_consistent",
        ))

        assert node1 in viewable  # manager implies view
        assert node2 in viewable  # viewer implies view
        assert node3 not in viewable

    def test_lookup_includes_inherited(self, hierarchy_schema):
        """LookupResources includes nodes accessible via inheritance."""
        adapter = hierarchy_schema
        user_id = uuid.uuid4().hex
        parent_id = uuid.uuid4().hex
        child_id = uuid.uuid4().hex

        adapter.write_tuples([
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{child_id}",
                relation="parent",
                subject=f"hierarchy_node:{parent_id}",
            )),
            TupleWrite(key=TupleKey(
                object=f"hierarchy_node:{parent_id}",
                relation="manager",
                subject=f"user:{user_id}",
            )),
        ])

        manageable = set(adapter.lookup_resources(
            subject=f"user:{user_id}",
            relation="manage",
            resource_type="hierarchy_node",
            consistency="fully_consistent",
        ))

        assert parent_id in manageable
        assert child_id in manageable  # via inheritance


# =============================================================================
# Full Integration Tests with Django Models
# =============================================================================


class TestFullHierarchyIntegration:
    """
    End-to-end tests with Django models and real SpiceDB.

    Tests the complete flow:
    1. Create hierarchy nodes (triggers signal -> writes tuples)
    2. Assign roles (triggers signal -> writes tuples)
    3. Check permissions via evaluator
    4. Query accessible nodes via accessible_by()
    """

    @pytest.mark.django_db
    def test_signal_writes_parent_tuple(
        self, configured_adapter, company, company_ct, hierarchy_types
    ):
        """Creating HierarchyNode with parent writes tuple to SpiceDB."""
        config = _hierarchy_config()
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            registry.refresh()

            region = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["region"],
                name="Test Region",
            )
            branch = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["branch"],
                name="Test Branch",
                parent=region,
            )

            # Verify tuple was written - assign a manager and check inheritance
            User = get_user_model()
            user = User.objects.create_user(
                username=f"test-{uuid.uuid4().hex[:8]}",
                password="pass",
            )

            # Direct assignment to region
            configured_adapter.write_tuples([
                TupleWrite(key=TupleKey(
                    object=f"hierarchy_node:{region.pk}",
                    relation="manager",
                    subject=f"user:{user.pk}",
                ))
            ])

            # Should be able to manage branch via inheritance
            assert configured_adapter.check(
                subject=f"user:{user.pk}",
                relation="manage",
                object_=f"hierarchy_node:{branch.pk}",
                consistency="fully_consistent",
            )

    @pytest.mark.django_db
    def test_signal_writes_role_tuple(
        self, configured_adapter, company, company_ct, hierarchy_types, users
    ):
        """Creating HierarchyNodeRole writes tuple to SpiceDB."""
        config = _hierarchy_config()
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            registry.refresh()

            region = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["region"],
                name="Signal Test Region",
            )

            # Create role assignment - this should trigger signal
            HierarchyNodeRole.objects.create(
                node=region,
                user=users["ceo"],
                role="owner",
            )

            # Verify tuple was written
            assert configured_adapter.check(
                subject=f"user:{users['ceo'].pk}",
                relation="owner",
                object_=f"hierarchy_node:{region.pk}",
                consistency="fully_consistent",
            )

    @pytest.mark.django_db
    def test_full_4_level_scenario(
        self, configured_adapter, company, company_ct, hierarchy_types, users
    ):
        """
        Full 4-level hierarchy test:
        - CEO (admin on region) sees everything
        - Regional manager sees region + all descendants
        - Branch manager sees branch + descendants only
        - Outsider sees nothing
        """
        config = _hierarchy_config()
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            registry.refresh()

            # Create hierarchy
            region = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["region"],
                name="North Region",
            )
            branch = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["branch"],
                name="Downtown Branch",
                parent=region,
            )
            dept = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["department"],
                name="Engineering",
                parent=branch,
            )
            team = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["team"],
                name="Team Alpha",
                parent=dept,
            )

            # Assign roles
            HierarchyNodeRole.objects.create(node=region, user=users["ceo"], role="owner")
            HierarchyNodeRole.objects.create(node=region, user=users["regional_mgr"], role="manager")
            HierarchyNodeRole.objects.create(node=branch, user=users["branch_mgr"], role="manager")
            HierarchyNodeRole.objects.create(node=dept, user=users["dept_head"], role="manager")
            HierarchyNodeRole.objects.create(node=team, user=users["team_lead"], role="lead")
            HierarchyNodeRole.objects.create(node=team, user=users["employee"], role="member")

            # Helper to check permission
            def can_view(user, node):
                return configured_adapter.check(
                    subject=f"user:{user.pk}",
                    relation="view",
                    object_=f"hierarchy_node:{node.pk}",
                    consistency="fully_consistent",
                )

            def can_manage(user, node):
                return configured_adapter.check(
                    subject=f"user:{user.pk}",
                    relation="manage",
                    object_=f"hierarchy_node:{node.pk}",
                    consistency="fully_consistent",
                )

            # CEO can view/manage everything
            for node in [region, branch, dept, team]:
                assert can_view(users["ceo"], node), f"CEO should view {node.name}"
                assert can_manage(users["ceo"], node), f"CEO should manage {node.name}"

            # Regional manager can view/manage region and all descendants
            for node in [region, branch, dept, team]:
                assert can_view(users["regional_mgr"], node)
                assert can_manage(users["regional_mgr"], node)

            # Branch manager can view/manage branch and descendants, not region
            assert not can_manage(users["branch_mgr"], region)
            for node in [branch, dept, team]:
                assert can_view(users["branch_mgr"], node)
                assert can_manage(users["branch_mgr"], node)

            # Dept head can view/manage dept and team, not branch/region
            assert not can_manage(users["dept_head"], region)
            assert not can_manage(users["dept_head"], branch)
            for node in [dept, team]:
                assert can_view(users["dept_head"], node)
                assert can_manage(users["dept_head"], node)

            # Team lead can manage team only
            assert can_manage(users["team_lead"], team)
            assert not can_manage(users["team_lead"], dept)

            # Employee can view team only (member role)
            assert can_view(users["employee"], team)
            assert not can_manage(users["employee"], team)
            assert not can_view(users["employee"], dept)

            # Outsider can view nothing
            for node in [region, branch, dept, team]:
                assert not can_view(users["outsider"], node)

    @pytest.mark.django_db
    def test_accessible_by_with_spicedb(
        self, configured_adapter, company, company_ct, hierarchy_types, users
    ):
        """Test accessible_by() queryset method with real SpiceDB."""
        config = _hierarchy_config()
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            registry.refresh()

            # Create nodes
            region1 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["region"],
                name="Region 1",
            )
            region2 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["region"],
                name="Region 2",
            )
            branch1 = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["branch"],
                name="Branch 1",
                parent=region1,
            )

            # User is manager of region1 only
            HierarchyNodeRole.objects.create(
                node=region1,
                user=users["regional_mgr"],
                role="manager",
            )

            # Debug: directly check SpiceDB permissions
            user_ref = f"user:{users['regional_mgr'].pk}"

            # Verify SpiceDB permission checks directly
            can_view_region1 = configured_adapter.check(
                subject=user_ref,
                relation="view",
                object_=f"hierarchy_node:{region1.pk}",
                consistency="fully_consistent",
            )
            can_view_region2 = configured_adapter.check(
                subject=user_ref,
                relation="view",
                object_=f"hierarchy_node:{region2.pk}",
                consistency="fully_consistent",
            )
            can_view_branch1 = configured_adapter.check(
                subject=user_ref,
                relation="view",
                object_=f"hierarchy_node:{branch1.pk}",
                consistency="fully_consistent",
            )

            assert can_view_region1, "User should be able to view region1"
            assert can_view_branch1, "User should be able to view branch1"
            assert not can_view_region2, "User should NOT be able to view region2"

            # Query accessible nodes with tenant context
            with tenant_context(company):
                accessible = HierarchyNode.objects.accessible_by(
                    users["regional_mgr"],
                    "view",
                    consistency="fully_consistent",
                )
                accessible_names = set(accessible.values_list("name", flat=True))

            # Should see region1 and branch1, not region2
            assert "Region 1" in accessible_names
            assert "Branch 1" in accessible_names
            assert "Region 2" not in accessible_names

    @pytest.mark.django_db
    def test_role_deletion_revokes_permission(
        self, configured_adapter, company, company_ct, hierarchy_types, users
    ):
        """Deleting HierarchyNodeRole revokes permission in SpiceDB."""
        config = _hierarchy_config()
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            registry.refresh()

            region = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["region"],
                name="Deletion Test Region",
            )

            role = HierarchyNodeRole.objects.create(
                node=region,
                user=users["ceo"],
                role="owner",
            )

            # Verify has permission
            assert configured_adapter.check(
                subject=f"user:{users['ceo'].pk}",
                relation="owner",
                object_=f"hierarchy_node:{region.pk}",
                consistency="fully_consistent",
            )

            # Delete role
            role.delete()

            # Verify permission revoked
            assert not configured_adapter.check(
                subject=f"user:{users['ceo'].pk}",
                relation="owner",
                object_=f"hierarchy_node:{region.pk}",
                consistency="fully_consistent",
            )
