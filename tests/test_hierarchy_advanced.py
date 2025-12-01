"""
Advanced TDD tests for multi-tenant hierarchy system.

This file tests:
1. Admin registration for hierarchy models
2. SpiceDB schema integration
3. Complex 4-level hierarchy with transaction access control

Scenario: Income Verification SaaS
- Level 0: CEO - sees all regions, branches, departments, and transactions
- Level 1: Regional Manager - sees their region's branches and all transactions within
- Level 2: Branch Manager - sees their branch's departments and transactions
- Level 3: Department Head - sees only their department's transactions

Each level can:
- View transactions within their scope
- See metrics/performance of their direct reports
- Compare performance across their subordinate units
"""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.models import HierarchyNode, HierarchyNodeRole, HierarchyTypeDefinition
from django_rebac.hierarchy.signals import connect_hierarchy_signals, disconnect_hierarchy_signals

from example_project.documents.models import Company


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def admin_site():
    """Django admin site instance."""
    return AdminSite()


@pytest.fixture
def tenant_settings():
    """Full tenant settings for complex hierarchy."""
    return {
        "tenant_model": "example_project.documents.models.Company",
        "tenant_fk_name": "company",
        "types": {
            "user": {"model": "django.contrib.auth.models.User"},
            "hierarchy_node": {
                "model": "django_rebac.models.HierarchyNode",
                "relations": {
                    "parent": "hierarchy_node",
                    "admin": "user",
                    "manager": "user",
                    "viewer": "user",
                },
                "permissions": {
                    "admin": "admin + parent->admin",
                    "manage": "manager + admin + parent->manage",
                    "view": "viewer + manage + parent->view",
                },
            },
        },
        "db_overrides": False,
    }


@pytest.fixture
def company(db):
    """Test company (tenant)."""
    return Company.objects.create(name="Acme Verification Services", slug="acme-vs")


@pytest.fixture
def company_ct(db):
    """ContentType for Company."""
    return ContentType.objects.get_for_model(Company)


@pytest.fixture
def hierarchy_types(company, company_ct):
    """
    Create 4-level hierarchy type definitions.

    Returns dict with: region_type, branch_type, department_type, team_type
    """
    region_type = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="region",
        display_name="Region",
        slug="region",
        level=0,
        relations={"admin": "user", "manager": "user", "viewer": "user"},
        permissions={
            "admin": "admin + parent->admin",
            "manage": "manager + admin + parent->manage",
            "view": "viewer + manage + parent->view",
        },
        icon="globe",
        color="#3B82F6",
    )

    branch_type = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="branch",
        display_name="Branch",
        slug="branch",
        level=1,
        parent_type=region_type,
        relations={"manager": "user", "viewer": "user"},
        permissions={
            "manage": "manager + parent->manage",
            "view": "viewer + manage + parent->view",
        },
        icon="building",
        color="#10B981",
    )

    department_type = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="department",
        display_name="Department",
        slug="department",
        level=2,
        parent_type=branch_type,
        relations={"manager": "user", "viewer": "user"},
        permissions={
            "manage": "manager + parent->manage",
            "view": "viewer + manage + parent->view",
        },
        icon="users",
        color="#F59E0B",
    )

    team_type = HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_ct,
        tenant_object_id=str(company.pk),
        name="team",
        display_name="Team",
        slug="team",
        level=3,
        parent_type=department_type,
        relations={"lead": "user", "member": "user"},
        permissions={
            "manage": "lead + parent->manage",
            "view": "member + manage + parent->view",
        },
        icon="user-group",
        color="#EF4444",
    )

    return {
        "region": region_type,
        "branch": branch_type,
        "department": department_type,
        "team": team_type,
    }


@pytest.fixture
def users(db):
    """
    Create test users at different hierarchy levels.

    Returns dict with: ceo, regional_mgr_north, regional_mgr_south,
                       branch_mgr_downtown, branch_mgr_uptown,
                       dept_head_engineering, dept_head_sales, team_lead, employee
    """
    User = get_user_model()

    return {
        "ceo": User.objects.create_user(username="ceo", password="pass"),
        "regional_mgr_north": User.objects.create_user(username="regional_north", password="pass"),
        "regional_mgr_south": User.objects.create_user(username="regional_south", password="pass"),
        "branch_mgr_downtown": User.objects.create_user(username="branch_downtown", password="pass"),
        "branch_mgr_uptown": User.objects.create_user(username="branch_uptown", password="pass"),
        "dept_head_engineering": User.objects.create_user(username="dept_engineering", password="pass"),
        "dept_head_sales": User.objects.create_user(username="dept_sales", password="pass"),
        "team_lead": User.objects.create_user(username="team_lead", password="pass"),
        "employee": User.objects.create_user(username="employee", password="pass"),
    }


# =============================================================================
# 1. Admin Registration Tests
# =============================================================================


class TestAdminRegistration:
    """
    Tests for Django admin registration of hierarchy models.

    Expected UX:
    - HierarchyTypeDefinition has list display with tenant, name, level
    - HierarchyNode has list display with name, type, parent, depth
    - HierarchyNodeRole is an inline on HierarchyNode admin
    - Filters for tenant, hierarchy type, parent
    """

    @pytest.mark.django_db
    def test_hierarchy_type_definition_admin_registered(self, admin_site):
        """HierarchyTypeDefinition should be registered in admin."""
        from django_rebac.admin import HierarchyTypeDefinitionAdmin

        admin_site.register(HierarchyTypeDefinition, HierarchyTypeDefinitionAdmin)
        assert HierarchyTypeDefinition in admin_site._registry

    @pytest.mark.django_db
    def test_hierarchy_type_definition_list_display(self, admin_site):
        """HierarchyTypeDefinition admin has proper list display."""
        from django_rebac.admin import HierarchyTypeDefinitionAdmin

        admin = HierarchyTypeDefinitionAdmin(HierarchyTypeDefinition, admin_site)

        assert "name" in admin.list_display
        assert "display_name" in admin.list_display
        assert "level" in admin.list_display
        assert "is_active" in admin.list_display

    @pytest.mark.django_db
    def test_hierarchy_type_definition_list_filter(self, admin_site):
        """HierarchyTypeDefinition admin has proper filters."""
        from django_rebac.admin import HierarchyTypeDefinitionAdmin

        admin = HierarchyTypeDefinitionAdmin(HierarchyTypeDefinition, admin_site)

        assert "tenant_content_type" in admin.list_filter
        assert "level" in admin.list_filter
        assert "is_active" in admin.list_filter

    @pytest.mark.django_db
    def test_hierarchy_node_admin_registered(self, admin_site):
        """HierarchyNode should be registered in admin."""
        from django_rebac.admin import HierarchyNodeAdmin

        admin_site.register(HierarchyNode, HierarchyNodeAdmin)
        assert HierarchyNode in admin_site._registry

    @pytest.mark.django_db
    def test_hierarchy_node_list_display(self, admin_site):
        """HierarchyNode admin has proper list display."""
        from django_rebac.admin import HierarchyNodeAdmin

        admin = HierarchyNodeAdmin(HierarchyNode, admin_site)

        assert "name" in admin.list_display
        assert "hierarchy_type" in admin.list_display
        assert "parent" in admin.list_display
        assert "depth" in admin.list_display

    @pytest.mark.django_db
    def test_hierarchy_node_has_role_inline(self, admin_site):
        """HierarchyNode admin has HierarchyNodeRole as inline."""
        from django_rebac.admin import HierarchyNodeAdmin, HierarchyNodeRoleInline

        admin = HierarchyNodeAdmin(HierarchyNode, admin_site)

        # inlines is a list of inline classes
        assert HierarchyNodeRoleInline in admin.inlines

    @pytest.mark.django_db
    def test_hierarchy_node_search_fields(self, admin_site):
        """HierarchyNode admin has searchable fields."""
        from django_rebac.admin import HierarchyNodeAdmin

        admin = HierarchyNodeAdmin(HierarchyNode, admin_site)

        assert "name" in admin.search_fields
        assert "slug" in admin.search_fields


# =============================================================================
# 2. SpiceDB Schema Integration Tests
# =============================================================================


class TestSpiceDBSchemaIntegration:
    """
    Tests for SpiceDB schema generation from hierarchy configuration.

    Expected UX:
    - hierarchy_node type auto-included when hierarchy models exist
    - Schema includes parent, manager, viewer relations
    - Permissions use proper arrow notation for inheritance
    """

    @pytest.mark.django_db
    def test_schema_includes_hierarchy_node_type(self, tenant_settings):
        """TypeGraph should include hierarchy_node type."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            graph = conf.get_type_graph()

            assert "hierarchy_node" in graph.types

    @pytest.mark.django_db
    def test_schema_hierarchy_node_relations(self, tenant_settings):
        """hierarchy_node type should have parent, manager, viewer relations."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            graph = conf.get_type_graph()

            hierarchy_type = graph.types["hierarchy_node"]

            assert "parent" in hierarchy_type.relations
            assert "manager" in hierarchy_type.relations
            assert "viewer" in hierarchy_type.relations

    @pytest.mark.django_db
    def test_schema_hierarchy_node_permissions(self, tenant_settings):
        """hierarchy_node type should have manage, view permissions with inheritance."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            graph = conf.get_type_graph()

            hierarchy_type = graph.types["hierarchy_node"]

            assert "manage" in hierarchy_type.permissions
            assert "view" in hierarchy_type.permissions
            # Check inheritance arrow notation
            assert "parent->manage" in hierarchy_type.permissions["manage"]
            assert "parent->view" in hierarchy_type.permissions["view"]

    @pytest.mark.django_db
    def test_compile_schema_includes_hierarchy(self, tenant_settings):
        """Compiled schema DSL should include hierarchy_node definition."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()
            graph = conf.get_type_graph()

            schema = graph.compile_schema()

            assert "definition hierarchy_node" in schema
            assert "relation parent:" in schema
            assert "permission manage =" in schema
            assert "permission view =" in schema


# =============================================================================
# 3. Complex 4-Level Hierarchy Integration Tests
# =============================================================================


class TestComplexHierarchyScenario:
    """
    Complex integration test simulating income verification SaaS.

    Hierarchy:
    - Acme Corp (tenant)
      - North Region (CEO + Regional Manager North)
        - Downtown Branch (Branch Manager Downtown)
          - Engineering Dept (Dept Head Engineering)
            - Team Alpha (Team Lead)
          - Sales Dept (Dept Head Sales)
        - Uptown Branch (Branch Manager Uptown)
      - South Region (Regional Manager South)
        - (empty for comparison tests)

    Test scenarios:
    - CEO sees all nodes and can compare regions
    - Regional Manager sees only their region
    - Branch Manager sees only their branch
    - Department Head sees only their department
    - Team Lead sees only their team
    - Cross-region access is denied
    """

    @pytest.fixture(autouse=True)
    def setup_signals(self):
        """Connect hierarchy signals."""
        connect_hierarchy_signals()
        yield
        disconnect_hierarchy_signals()

    @pytest.fixture
    def full_hierarchy(self, company, company_ct, hierarchy_types, users):
        """
        Create complete 4-level hierarchy with role assignments.

        Returns dict with all nodes.
        """
        # Level 0: Regions
        north_region = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["region"],
            name="North Region",
            slug="north-region",
        )
        south_region = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["region"],
            name="South Region",
            slug="south-region",
        )

        # Level 1: Branches
        downtown_branch = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["branch"],
            name="Downtown Branch",
            slug="downtown-branch",
            parent=north_region,
        )
        uptown_branch = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["branch"],
            name="Uptown Branch",
            slug="uptown-branch",
            parent=north_region,
        )

        # Level 2: Departments
        engineering_dept = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["department"],
            name="Engineering Department",
            slug="engineering-dept",
            parent=downtown_branch,
        )
        sales_dept = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["department"],
            name="Sales Department",
            slug="sales-dept",
            parent=downtown_branch,
        )

        # Level 3: Teams
        team_alpha = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["team"],
            name="Team Alpha",
            slug="team-alpha",
            parent=engineering_dept,
        )

        # Assign roles
        # CEO is admin at company level (both regions)
        HierarchyNodeRole.objects.create(
            node=north_region, user=users["ceo"], role="admin"
        )
        HierarchyNodeRole.objects.create(
            node=south_region, user=users["ceo"], role="admin"
        )

        # Regional managers
        HierarchyNodeRole.objects.create(
            node=north_region, user=users["regional_mgr_north"], role="manager"
        )
        HierarchyNodeRole.objects.create(
            node=south_region, user=users["regional_mgr_south"], role="manager"
        )

        # Branch managers
        HierarchyNodeRole.objects.create(
            node=downtown_branch, user=users["branch_mgr_downtown"], role="manager"
        )
        HierarchyNodeRole.objects.create(
            node=uptown_branch, user=users["branch_mgr_uptown"], role="manager"
        )

        # Department heads
        HierarchyNodeRole.objects.create(
            node=engineering_dept, user=users["dept_head_engineering"], role="manager"
        )
        HierarchyNodeRole.objects.create(
            node=sales_dept, user=users["dept_head_sales"], role="manager"
        )

        # Team lead
        HierarchyNodeRole.objects.create(
            node=team_alpha, user=users["team_lead"], role="lead"
        )

        # Employee is just a member
        HierarchyNodeRole.objects.create(
            node=team_alpha, user=users["employee"], role="member"
        )

        return {
            "north_region": north_region,
            "south_region": south_region,
            "downtown_branch": downtown_branch,
            "uptown_branch": uptown_branch,
            "engineering_dept": engineering_dept,
            "sales_dept": sales_dept,
            "team_alpha": team_alpha,
        }

    @pytest.mark.django_db
    def test_ceo_can_view_all_nodes(
        self, tenant_settings, recording_adapter, company, users, full_hierarchy
    ):
        """CEO with admin role on both regions can view all nodes."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # Mock SpiceDB - CEO can view everything
            all_node_ids = [str(n.pk) for n in full_hierarchy.values()]
            recording_adapter.set_lookup_response(
                subject=f"user:{users['ceo'].pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=all_node_ids,
            )

            from django_rebac.tenant import tenant_context

            with tenant_context(company):
                qs = HierarchyNode.objects.accessible_by(users["ceo"], "view")
                accessible_names = set(qs.values_list("name", flat=True))

            assert "North Region" in accessible_names
            assert "South Region" in accessible_names
            assert "Downtown Branch" in accessible_names
            assert "Engineering Department" in accessible_names
            assert "Team Alpha" in accessible_names

    @pytest.mark.django_db
    def test_regional_manager_sees_only_their_region(
        self, tenant_settings, recording_adapter, company, users, full_hierarchy
    ):
        """Regional Manager North sees only North Region hierarchy."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # North region includes: north_region, downtown, uptown, engineering, sales, team_alpha
            north_nodes = [
                full_hierarchy["north_region"],
                full_hierarchy["downtown_branch"],
                full_hierarchy["uptown_branch"],
                full_hierarchy["engineering_dept"],
                full_hierarchy["sales_dept"],
                full_hierarchy["team_alpha"],
            ]

            recording_adapter.set_lookup_response(
                subject=f"user:{users['regional_mgr_north'].pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=[str(n.pk) for n in north_nodes],
            )

            from django_rebac.tenant import tenant_context

            with tenant_context(company):
                qs = HierarchyNode.objects.accessible_by(users["regional_mgr_north"], "view")
                accessible_names = set(qs.values_list("name", flat=True))

            # Should see North Region hierarchy
            assert "North Region" in accessible_names
            assert "Downtown Branch" in accessible_names
            assert "Engineering Department" in accessible_names

            # Should NOT see South Region
            assert "South Region" not in accessible_names

    @pytest.mark.django_db
    def test_branch_manager_sees_only_their_branch(
        self, tenant_settings, recording_adapter, company, users, full_hierarchy
    ):
        """Branch Manager Downtown sees only Downtown Branch hierarchy."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # Downtown branch includes: downtown, engineering, sales, team_alpha
            downtown_nodes = [
                full_hierarchy["downtown_branch"],
                full_hierarchy["engineering_dept"],
                full_hierarchy["sales_dept"],
                full_hierarchy["team_alpha"],
            ]

            recording_adapter.set_lookup_response(
                subject=f"user:{users['branch_mgr_downtown'].pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=[str(n.pk) for n in downtown_nodes],
            )

            from django_rebac.tenant import tenant_context

            with tenant_context(company):
                qs = HierarchyNode.objects.accessible_by(users["branch_mgr_downtown"], "view")
                accessible_names = set(qs.values_list("name", flat=True))

            # Should see Downtown Branch hierarchy
            assert "Downtown Branch" in accessible_names
            assert "Engineering Department" in accessible_names
            assert "Sales Department" in accessible_names

            # Should NOT see Uptown or parent regions
            assert "Uptown Branch" not in accessible_names
            assert "North Region" not in accessible_names

    @pytest.mark.django_db
    def test_department_head_sees_only_their_department(
        self, tenant_settings, recording_adapter, company, users, full_hierarchy
    ):
        """Department Head Engineering sees only Engineering Department."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # Engineering dept includes: engineering, team_alpha
            eng_nodes = [
                full_hierarchy["engineering_dept"],
                full_hierarchy["team_alpha"],
            ]

            recording_adapter.set_lookup_response(
                subject=f"user:{users['dept_head_engineering'].pk}",
                relation="view",
                resource_type="hierarchy_node",
                results=[str(n.pk) for n in eng_nodes],
            )

            from django_rebac.tenant import tenant_context

            with tenant_context(company):
                qs = HierarchyNode.objects.accessible_by(users["dept_head_engineering"], "view")
                accessible_names = set(qs.values_list("name", flat=True))

            # Should see Engineering hierarchy
            assert "Engineering Department" in accessible_names
            assert "Team Alpha" in accessible_names

            # Should NOT see Sales or parent nodes
            assert "Sales Department" not in accessible_names
            assert "Downtown Branch" not in accessible_names

    @pytest.mark.django_db
    def test_tuples_written_for_full_hierarchy(
        self, tenant_settings, recording_adapter, company, company_ct, hierarchy_types, users
    ):
        """All parent and role tuples are written when hierarchy is created."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # Create a simple 2-level hierarchy
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

            # Assign manager role
            HierarchyNodeRole.objects.create(
                node=region,
                user=users["ceo"],
                role="manager",
            )

            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }

            # Parent tuple
            assert (
                f"hierarchy_node:{branch.pk}",
                "parent",
                f"hierarchy_node:{region.pk}",
            ) in write_tuples

            # Role tuple
            assert (
                f"hierarchy_node:{region.pk}",
                "manager",
                f"user:{users['ceo'].pk}",
            ) in write_tuples

    @pytest.mark.django_db
    def test_cross_tenant_access_denied(
        self, tenant_settings, recording_adapter, company, company_ct, hierarchy_types, users
    ):
        """User cannot access nodes from another tenant."""
        with override_settings(REBAC=tenant_settings):
            conf.reset_type_graph_cache()

            # Create another company
            other_company = Company.objects.create(name="Other Corp", slug="other")

            # Create node in original company
            node = HierarchyNode.objects.create(
                tenant_content_type=company_ct,
                tenant_object_id=str(company.pk),
                hierarchy_type=hierarchy_types["region"],
                name="Acme Region",
            )

            from django_rebac.tenant import TenantAwarePermissionEvaluator

            # Try to access from other company context
            evaluator = TenantAwarePermissionEvaluator(users["ceo"], tenant=other_company)

            # Should be denied without hitting SpiceDB
            assert evaluator.can("view", node) is False
            assert len(recording_adapter.check_calls) == 0

    @pytest.mark.django_db
    def test_hierarchy_path_calculation(self, company, company_ct, hierarchy_types):
        """Nodes have correct materialized path for efficient queries."""
        region = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["region"],
            name="Region",
        )
        branch = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["branch"],
            name="Branch",
            parent=region,
        )
        dept = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["department"],
            name="Dept",
            parent=branch,
        )
        team = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["team"],
            name="Team",
            parent=dept,
        )

        # Verify paths
        assert region.path == f"/{region.pk}/"
        assert branch.path == f"/{region.pk}/{branch.pk}/"
        assert dept.path == f"/{region.pk}/{branch.pk}/{dept.pk}/"
        assert team.path == f"/{region.pk}/{branch.pk}/{dept.pk}/{team.pk}/"

        # Verify depths
        assert region.depth == 0
        assert branch.depth == 1
        assert dept.depth == 2
        assert team.depth == 3

    @pytest.mark.django_db
    def test_get_descendants_for_metrics(self, company, company_ct, hierarchy_types):
        """
        Can get all descendants for aggregating metrics.

        Use case: Regional Manager wants to see performance of all branches.
        """
        region = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["region"],
            name="Region",
        )
        branch1 = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["branch"],
            name="Branch 1",
            parent=region,
        )
        branch2 = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["branch"],
            name="Branch 2",
            parent=region,
        )
        dept1 = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["department"],
            name="Dept 1",
            parent=branch1,
        )

        # Regional manager can get all descendants
        descendants = region.get_descendants()
        descendant_names = set(descendants.values_list("name", flat=True))

        assert "Branch 1" in descendant_names
        assert "Branch 2" in descendant_names
        assert "Dept 1" in descendant_names
        assert len(descendant_names) == 3

    @pytest.mark.django_db
    def test_compare_branches_at_same_level(self, company, company_ct, hierarchy_types):
        """
        Can filter nodes at same level for comparison.

        Use case: CEO wants to compare performance across regions.
        """
        region1 = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["region"],
            name="North Region",
        )
        region2 = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["region"],
            name="South Region",
        )
        branch1 = HierarchyNode.objects.create(
            tenant_content_type=company_ct,
            tenant_object_id=str(company.pk),
            hierarchy_type=hierarchy_types["branch"],
            name="Branch A",
            parent=region1,
        )

        # Get all regions (depth=0) for comparison
        from django.contrib.contenttypes.models import ContentType
        tenant_ct = ContentType.objects.get_for_model(company)

        regions = HierarchyNode.objects.filter(
            tenant_content_type=tenant_ct,
            tenant_object_id=str(company.pk),
            depth=0,
        )

        region_names = set(regions.values_list("name", flat=True))
        assert region_names == {"North Region", "South Region"}
        assert "Branch A" not in region_names
