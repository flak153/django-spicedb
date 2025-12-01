"""Tests for multi-tenant hierarchy models."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError

from django_rebac.models import (
    HierarchyNode,
    HierarchyNodeRole,
    HierarchyTypeDefinition,
)

from example_project.documents.models import Company


@pytest.fixture
def company(db):
    """Create a test company (tenant)."""
    return Company.objects.create(name="Acme Corp", slug="acme")


@pytest.fixture
def other_company(db):
    """Create another test company for isolation tests."""
    return Company.objects.create(name="Other Corp", slug="other")


@pytest.fixture
def company_content_type(db):
    """Get the ContentType for Company model."""
    return ContentType.objects.get_for_model(Company)


@pytest.fixture
def region_type(company, company_content_type):
    """Create a Region hierarchy type for the company."""
    return HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_content_type,
        tenant_object_id=str(company.pk),
        name="region",
        display_name="Region",
        slug="region",
        level=0,
        parent_type=None,
        relations={"manager": "user", "viewer": "user"},
        permissions={"manage": "manager + parent->manage", "view": "viewer + manage"},
    )


@pytest.fixture
def branch_type(company, company_content_type, region_type):
    """Create a Branch hierarchy type under Region."""
    return HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_content_type,
        tenant_object_id=str(company.pk),
        name="branch",
        display_name="Branch",
        slug="branch",
        level=1,
        parent_type=region_type,
        relations={"manager": "user", "viewer": "user"},
        permissions={"manage": "manager + parent->manage", "view": "viewer + manage"},
    )


@pytest.fixture
def department_type(company, company_content_type, branch_type):
    """Create a Department hierarchy type under Branch."""
    return HierarchyTypeDefinition.objects.create(
        tenant_content_type=company_content_type,
        tenant_object_id=str(company.pk),
        name="department",
        display_name="Department",
        slug="department",
        level=2,
        parent_type=branch_type,
        relations={"manager": "user", "viewer": "user"},
        permissions={"manage": "manager + parent->manage", "view": "viewer + manage"},
    )


# =============================================================================
# HierarchyTypeDefinition Tests
# =============================================================================


class TestHierarchyTypeDefinition:
    """Tests for HierarchyTypeDefinition model."""

    @pytest.mark.django_db
    def test_create_hierarchy_type(self, company, company_content_type):
        """Can create a hierarchy type for a tenant."""
        ht = HierarchyTypeDefinition.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            name="region",
            display_name="Region",
            slug="region",
            level=0,
        )
        assert ht.pk is not None
        assert ht.name == "region"
        assert ht.display_name == "Region"
        assert ht.level == 0
        assert ht.parent_type is None

    @pytest.mark.django_db
    def test_spicedb_type_name(self, region_type):
        """spicedb_type_name returns the global hierarchy_node type."""
        assert region_type.spicedb_type_name == "hierarchy_node"

    @pytest.mark.django_db
    def test_str_representation(self, region_type):
        """String representation shows display name and level."""
        assert str(region_type) == "Region (level 0)"

    @pytest.mark.django_db
    def test_unique_slug_per_tenant(self, company, company_content_type, region_type):
        """Slug must be unique within a tenant."""
        with pytest.raises(IntegrityError):
            HierarchyTypeDefinition.objects.create(
                tenant_content_type=company_content_type,
                tenant_object_id=str(company.pk),
                name="another-region",
                display_name="Another Region",
                slug="region",  # Same slug as region_type
                level=0,
            )

    @pytest.mark.django_db
    def test_same_slug_different_tenant(
        self, company, other_company, company_content_type
    ):
        """Same slug can be used by different tenants."""
        HierarchyTypeDefinition.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            name="region",
            display_name="Region",
            slug="region",
            level=0,
        )
        # Should not raise - different tenant
        ht2 = HierarchyTypeDefinition.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(other_company.pk),
            name="region",
            display_name="Region",
            slug="region",
            level=0,
        )
        assert ht2.pk is not None

    @pytest.mark.django_db
    def test_parent_type_chain(self, region_type, branch_type, department_type):
        """Parent types form a proper chain."""
        assert region_type.parent_type is None
        assert branch_type.parent_type == region_type
        assert department_type.parent_type == branch_type

    @pytest.mark.django_db
    def test_relations_and_permissions_json(self, region_type):
        """Relations and permissions are stored as JSON."""
        assert region_type.relations == {"manager": "user", "viewer": "user"}
        assert region_type.permissions == {
            "manage": "manager + parent->manage",
            "view": "viewer + manage",
        }


# =============================================================================
# HierarchyNode Path/Depth Tests
# =============================================================================


class TestHierarchyNodePathDepth:
    """Tests for HierarchyNode path and depth calculation."""

    @pytest.mark.django_db
    def test_root_node_path_and_depth(self, company, company_content_type, region_type):
        """Root node has depth 0 and path /{pk}/."""
        node = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
        )
        assert node.depth == 0
        assert node.path == f"/{node.pk}/"

    @pytest.mark.django_db
    def test_child_node_path_and_depth(
        self, company, company_content_type, region_type, branch_type
    ):
        """Child node has depth parent.depth + 1 and path parent.path + pk."""
        root = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
        )
        child = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=branch_type,
            name="Downtown Branch",
            parent=root,
        )
        assert child.depth == 1
        assert child.path == f"/{root.pk}/{child.pk}/"

    @pytest.mark.django_db
    def test_grandchild_node_path_and_depth(
        self, company, company_content_type, region_type, branch_type, department_type
    ):
        """Grandchild has correct path and depth."""
        root = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
        )
        child = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=branch_type,
            name="Downtown Branch",
            parent=root,
        )
        grandchild = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=department_type,
            name="Engineering",
            parent=child,
        )
        assert grandchild.depth == 2
        assert grandchild.path == f"/{root.pk}/{child.pk}/{grandchild.pk}/"

    @pytest.mark.django_db
    def test_spicedb_object_ref(self, company, company_content_type, region_type):
        """spicedb_object_ref returns hierarchy_node:{pk}."""
        node = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
        )
        assert node.spicedb_object_ref == f"hierarchy_node:{node.pk}"


# =============================================================================
# HierarchyNode Ancestor/Descendant Tests
# =============================================================================


class TestHierarchyNodeQueries:
    """Tests for HierarchyNode ancestor and descendant queries."""

    @pytest.fixture
    def hierarchy_tree(
        self, company, company_content_type, region_type, branch_type, department_type
    ):
        """Create a hierarchy tree for testing.

        Structure:
        - North Region
          - Downtown Branch
            - Engineering Dept
            - Sales Dept
          - Uptown Branch
        - South Region
        """
        north = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
        )
        downtown = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=branch_type,
            name="Downtown Branch",
            parent=north,
        )
        engineering = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=department_type,
            name="Engineering",
            parent=downtown,
        )
        sales = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=department_type,
            name="Sales",
            parent=downtown,
        )
        uptown = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=branch_type,
            name="Uptown Branch",
            parent=north,
        )
        south = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="South Region",
        )
        return {
            "north": north,
            "downtown": downtown,
            "engineering": engineering,
            "sales": sales,
            "uptown": uptown,
            "south": south,
        }

    @pytest.mark.django_db
    def test_get_ancestors_excludes_self(self, hierarchy_tree):
        """get_ancestors() excludes self by default."""
        engineering = hierarchy_tree["engineering"]
        downtown = hierarchy_tree["downtown"]
        north = hierarchy_tree["north"]

        ancestors = list(engineering.get_ancestors())
        assert len(ancestors) == 2
        assert ancestors[0] == north  # Ordered by depth
        assert ancestors[1] == downtown

    @pytest.mark.django_db
    def test_get_ancestors_includes_self(self, hierarchy_tree):
        """get_ancestors(include_self=True) includes self."""
        engineering = hierarchy_tree["engineering"]
        ancestors = list(engineering.get_ancestors(include_self=True))
        assert len(ancestors) == 3
        assert engineering in ancestors

    @pytest.mark.django_db
    def test_get_ancestors_root_node(self, hierarchy_tree):
        """Root node has no ancestors."""
        north = hierarchy_tree["north"]
        ancestors = list(north.get_ancestors())
        assert len(ancestors) == 0

    @pytest.mark.django_db
    def test_get_descendants_excludes_self(self, hierarchy_tree):
        """get_descendants() excludes self by default."""
        north = hierarchy_tree["north"]
        downtown = hierarchy_tree["downtown"]
        engineering = hierarchy_tree["engineering"]
        sales = hierarchy_tree["sales"]
        uptown = hierarchy_tree["uptown"]

        descendants = list(north.get_descendants())
        assert len(descendants) == 4
        assert downtown in descendants
        assert engineering in descendants
        assert sales in descendants
        assert uptown in descendants
        assert north not in descendants

    @pytest.mark.django_db
    def test_get_descendants_includes_self(self, hierarchy_tree):
        """get_descendants(include_self=True) includes self."""
        north = hierarchy_tree["north"]
        descendants = list(north.get_descendants(include_self=True))
        assert len(descendants) == 5
        assert north in descendants

    @pytest.mark.django_db
    def test_get_descendants_leaf_node(self, hierarchy_tree):
        """Leaf node has no descendants."""
        engineering = hierarchy_tree["engineering"]
        descendants = list(engineering.get_descendants())
        assert len(descendants) == 0

    @pytest.mark.django_db
    def test_get_descendants_mid_level(self, hierarchy_tree):
        """Mid-level node returns only its subtree."""
        downtown = hierarchy_tree["downtown"]
        engineering = hierarchy_tree["engineering"]
        sales = hierarchy_tree["sales"]

        descendants = list(downtown.get_descendants())
        assert len(descendants) == 2
        assert engineering in descendants
        assert sales in descendants


# =============================================================================
# HierarchyNode Constraints Tests
# =============================================================================


class TestHierarchyNodeConstraints:
    """Tests for HierarchyNode constraints."""

    @pytest.mark.django_db
    def test_unique_slug_per_tenant_when_not_empty(
        self, company, company_content_type, region_type
    ):
        """Non-empty slug must be unique within tenant."""
        HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
            slug="north",
        )
        with pytest.raises(IntegrityError):
            HierarchyNode.objects.create(
                tenant_content_type=company_content_type,
                tenant_object_id=str(company.pk),
                hierarchy_type=region_type,
                name="Another North",
                slug="north",  # Duplicate slug
            )

    @pytest.mark.django_db
    def test_empty_slug_allowed_multiple(
        self, company, company_content_type, region_type
    ):
        """Multiple nodes can have empty slug."""
        node1 = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
            slug="",  # Empty slug
        )
        node2 = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="South Region",
            slug="",  # Empty slug
        )
        assert node1.pk is not None
        assert node2.pk is not None

    @pytest.mark.django_db
    def test_same_slug_different_tenant(
        self, company, other_company, company_content_type, region_type
    ):
        """Same slug can be used by different tenants."""
        HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
            slug="north",
        )
        # Create type for other company
        other_region_type = HierarchyTypeDefinition.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(other_company.pk),
            name="region",
            display_name="Region",
            slug="region",
            level=0,
        )
        # Should not raise - different tenant
        node2 = HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(other_company.pk),
            hierarchy_type=other_region_type,
            name="North Region",
            slug="north",
        )
        assert node2.pk is not None


# =============================================================================
# HierarchyNodeRole Tests
# =============================================================================


class TestHierarchyNodeRole:
    """Tests for HierarchyNodeRole model."""

    @pytest.fixture
    def user(self, db):
        """Create a test user."""
        User = get_user_model()
        return User.objects.create_user(username="testuser", password="password")

    @pytest.fixture
    def other_user(self, db):
        """Create another test user."""
        User = get_user_model()
        return User.objects.create_user(username="otheruser", password="password")

    @pytest.fixture
    def node(self, company, company_content_type, region_type):
        """Create a test hierarchy node."""
        return HierarchyNode.objects.create(
            tenant_content_type=company_content_type,
            tenant_object_id=str(company.pk),
            hierarchy_type=region_type,
            name="North Region",
        )

    @pytest.mark.django_db
    def test_create_role_assignment(self, node, user):
        """Can create a role assignment."""
        role = HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_MANAGER,
        )
        assert role.pk is not None
        assert role.node == node
        assert role.user == user
        assert role.role == "manager"
        assert role.inheritable is True  # Default

    @pytest.mark.django_db
    def test_str_representation(self, node, user):
        """String representation shows user, role, and node."""
        role = HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_MANAGER,
        )
        assert str(role) == f"{user} is manager on {node}"

    @pytest.mark.django_db
    def test_unique_node_user_role(self, node, user):
        """Cannot assign same role twice to same user on same node."""
        HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_MANAGER,
        )
        with pytest.raises(IntegrityError):
            HierarchyNodeRole.objects.create(
                node=node,
                user=user,
                role=HierarchyNodeRole.ROLE_MANAGER,
            )

    @pytest.mark.django_db
    def test_different_roles_same_user_node(self, node, user):
        """Same user can have different roles on same node."""
        role1 = HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_MANAGER,
        )
        role2 = HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_VIEWER,
        )
        assert role1.pk != role2.pk

    @pytest.mark.django_db
    def test_same_role_different_users(self, node, user, other_user):
        """Different users can have same role on same node."""
        role1 = HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_MANAGER,
        )
        role2 = HierarchyNodeRole.objects.create(
            node=node,
            user=other_user,
            role=HierarchyNodeRole.ROLE_MANAGER,
        )
        assert role1.pk != role2.pk

    @pytest.mark.django_db
    def test_inheritable_flag(self, node, user):
        """Can set inheritable flag to False."""
        role = HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_VIEWER,
            inheritable=False,
        )
        assert role.inheritable is False

    @pytest.mark.django_db
    def test_created_by_tracking(self, node, user, other_user):
        """Can track who created the role assignment."""
        role = HierarchyNodeRole.objects.create(
            node=node,
            user=user,
            role=HierarchyNodeRole.ROLE_MANAGER,
            created_by=other_user,
        )
        assert role.created_by == other_user

    @pytest.mark.django_db
    def test_role_choices(self, node, user):
        """All role choices are valid."""
        for role_value, role_display in HierarchyNodeRole.ROLE_CHOICES:
            role = HierarchyNodeRole.objects.create(
                node=node,
                user=user,
                role=role_value,
            )
            assert role.role == role_value
            # Clean up for next iteration
            role.delete()
