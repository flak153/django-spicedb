"""Tests for the Group/Verification pattern using custom Group model."""

import pytest
from django.contrib.auth import get_user_model

import django_rebac.conf as conf
from django_rebac.sync import registry

from example_project.documents.models import Group, GroupMembership, Verification


User = get_user_model()


@pytest.fixture
def rebac_setup(recording_adapter):
    """Setup fixture for Group/Verification tests."""
    conf.reset_type_graph_cache()
    registry.refresh()
    yield recording_adapter
    conf.reset_type_graph_cache()
    registry.refresh()


@pytest.mark.django_db
class TestGroupRegistration:
    """Test that custom Group model is properly registered as a ReBAC type."""

    def test_group_type_in_graph(self, rebac_setup):
        """Group should be registered in the type graph."""
        graph = conf.get_type_graph()
        assert "group" in graph.types

    def test_group_has_member_relation(self, rebac_setup):
        """Group should have member relation."""
        graph = conf.get_type_graph()
        group_type = graph.types["group"]
        assert "member" in group_type.relations
        assert group_type.relations["member"] == "user"

    def test_group_has_manager_relation(self, rebac_setup):
        """Group should have manager relation."""
        graph = conf.get_type_graph()
        group_type = graph.types["group"]
        assert "manager" in group_type.relations
        assert group_type.relations["manager"] == "user"

    def test_group_has_view_permission(self, rebac_setup):
        """Group should have view permission for member + manager."""
        graph = conf.get_type_graph()
        group_type = graph.types["group"]
        assert "view" in group_type.permissions
        assert group_type.permissions["view"] == "member + manager"

    def test_group_has_manage_permission(self, rebac_setup):
        """Group should have manage permission for manager only."""
        graph = conf.get_type_graph()
        group_type = graph.types["group"]
        assert "manage" in group_type.permissions
        assert group_type.permissions["manage"] == "manager"


@pytest.mark.django_db
class TestVerificationRegistration:
    """Test that Verification is properly registered as a ReBAC type."""

    def test_verification_type_in_graph(self, rebac_setup):
        """Verification should be registered in the type graph."""
        graph = conf.get_type_graph()
        assert "verification" in graph.types

    def test_verification_has_owner_relation(self, rebac_setup):
        """Verification should have owner relation."""
        graph = conf.get_type_graph()
        verification_type = graph.types["verification"]
        assert "owner" in verification_type.relations
        assert verification_type.relations["owner"] == "user"

    def test_verification_has_parent_relation_to_group(self, rebac_setup):
        """Verification should have parent relation pointing to group."""
        graph = conf.get_type_graph()
        verification_type = graph.types["verification"]
        assert "parent" in verification_type.relations
        assert verification_type.relations["parent"] == "group"

    def test_verification_inherits_permissions_from_parent(self, rebac_setup):
        """Verification permissions should reference parent->view and parent->manage."""
        graph = conf.get_type_graph()
        verification_type = graph.types["verification"]
        assert "view" in verification_type.permissions
        assert "parent->view" in verification_type.permissions["view"]
        assert "manage" in verification_type.permissions
        assert "parent->manage" in verification_type.permissions["manage"]


@pytest.mark.django_db(transaction=True)
class TestVerificationTupleSync:
    """Test that Verification creates correct tuples."""

    def test_verification_writes_owner_tuple(self, rebac_setup):
        """Creating a verification should write owner tuple."""
        user = User.objects.create_user(username="owner", password="pass")
        group = Group.objects.create(name="Engineering")

        verification = Verification.objects.create(
            title="Income Verification #1",
            owner=user,
            group=group,
        )

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }

        assert (
            f"verification:{verification.pk}",
            "owner",
            f"user:{user.pk}",
        ) in write_tuples

    def test_verification_writes_parent_tuple(self, rebac_setup):
        """Creating a verification should write parent (group) tuple."""
        user = User.objects.create_user(username="owner", password="pass")
        group = Group.objects.create(name="Engineering")

        verification = Verification.objects.create(
            title="Income Verification #1",
            owner=user,
            group=group,
        )

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }

        assert (
            f"verification:{verification.pk}",
            "parent",
            f"group:{group.pk}",
        ) in write_tuples


@pytest.mark.django_db
class TestGroupPermissionChecks:
    """Test permission checks with mocked adapter."""

    def test_owner_can_view_verification(self, rebac_setup):
        """Owner should be able to view their verification."""
        user = User.objects.create_user(username="owner", password="pass")
        group = Group.objects.create(name="Engineering")

        verification = Verification.objects.create(
            title="Test",
            owner=user,
            group=group,
        )

        # Mock the check response
        rebac_setup.set_check_response(
            subject=f"user:{user.pk}",
            relation="view",
            object_ref=f"verification:{verification.pk}",
            result=True,
        )

        assert verification.has_perm(user, "view")

    def test_group_member_can_view_verification(self, rebac_setup):
        """Group member should be able to view verification."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        group = Group.objects.create(name="Engineering")

        verification = Verification.objects.create(
            title="Test",
            owner=owner,
            group=group,
        )

        # Mock: member can view (via group membership)
        rebac_setup.set_check_response(
            subject=f"user:{member.pk}",
            relation="view",
            object_ref=f"verification:{verification.pk}",
            result=True,
        )

        assert verification.has_perm(member, "view")

    def test_group_manager_can_manage_verification(self, rebac_setup):
        """Group manager should be able to manage verification."""
        owner = User.objects.create_user(username="owner", password="pass")
        manager = User.objects.create_user(username="manager", password="pass")
        group = Group.objects.create(name="Engineering")

        verification = Verification.objects.create(
            title="Test",
            owner=owner,
            group=group,
        )

        # Mock: manager can manage (via group manager role)
        rebac_setup.set_check_response(
            subject=f"user:{manager.pk}",
            relation="manage",
            object_ref=f"verification:{verification.pk}",
            result=True,
        )

        assert verification.has_perm(manager, "manage")

    def test_non_member_cannot_view_verification(self, rebac_setup):
        """User not in group should not be able to view verification."""
        owner = User.objects.create_user(username="owner", password="pass")
        outsider = User.objects.create_user(username="outsider", password="pass")
        group = Group.objects.create(name="Engineering")

        verification = Verification.objects.create(
            title="Test",
            owner=owner,
            group=group,
        )

        # Mock: outsider cannot view
        rebac_setup.set_check_response(
            subject=f"user:{outsider.pk}",
            relation="view",
            object_ref=f"verification:{verification.pk}",
            result=False,
        )

        assert not verification.has_perm(outsider, "view")


@pytest.mark.django_db
class TestSchemaCompilation:
    """Test that the schema compiles correctly with Group/Verification."""

    def test_schema_includes_group_definition(self, rebac_setup):
        """Compiled schema should include group definition."""
        graph = conf.get_type_graph()
        schema = graph.compile_schema()

        assert "definition group" in schema
        assert "relation member: user" in schema
        assert "relation manager: user" in schema

    def test_schema_includes_verification_definition(self, rebac_setup):
        """Compiled schema should include verification definition."""
        graph = conf.get_type_graph()
        schema = graph.compile_schema()

        assert "definition verification" in schema
        assert "relation owner: user" in schema
        assert "relation parent: group" in schema


@pytest.mark.django_db(transaction=True)
class TestGroupMembershipTupleSync:
    """Test that GroupMembership syncs tuples to SpiceDB."""

    def test_membership_creates_member_tuple(self, rebac_setup):
        """Creating a member membership should write member tuple."""
        user = User.objects.create_user(username="member", password="pass")
        group = Group.objects.create(name="Engineering", slug="engineering")

        membership = GroupMembership.objects.create(
            group=group,
            user=user,
            role=GroupMembership.ROLE_MEMBER,
        )

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }

        assert (
            f"group:{group.pk}",
            "member",
            f"user:{user.pk}",
        ) in write_tuples

    def test_membership_creates_manager_tuple(self, rebac_setup):
        """Creating a manager membership should write manager tuple."""
        user = User.objects.create_user(username="manager", password="pass")
        group = Group.objects.create(name="Engineering", slug="engineering")

        membership = GroupMembership.objects.create(
            group=group,
            user=user,
            role=GroupMembership.ROLE_MANAGER,
        )

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }

        assert (
            f"group:{group.pk}",
            "manager",
            f"user:{user.pk}",
        ) in write_tuples

    def test_membership_role_change_deletes_old_tuple(self, rebac_setup):
        """Changing role should delete old tuple and create new one."""
        user = User.objects.create_user(username="user", password="pass")
        group = Group.objects.create(name="Engineering", slug="engineering")

        # Create as member
        membership = GroupMembership.objects.create(
            group=group,
            user=user,
            role=GroupMembership.ROLE_MEMBER,
        )

        # Clear recorded writes
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change to manager
        membership.role = GroupMembership.ROLE_MANAGER
        membership.save()

        # Check old tuple deleted
        delete_tuples = {
            (d.object, d.relation, d.subject)
            for d in rebac_setup.deletes
        }
        assert (
            f"group:{group.pk}",
            "member",
            f"user:{user.pk}",
        ) in delete_tuples

        # Check new tuple written
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (
            f"group:{group.pk}",
            "manager",
            f"user:{user.pk}",
        ) in write_tuples

    def test_membership_delete_removes_tuple(self, rebac_setup):
        """Deleting membership should remove tuple."""
        user = User.objects.create_user(username="user", password="pass")
        group = Group.objects.create(name="Engineering", slug="engineering")

        membership = GroupMembership.objects.create(
            group=group,
            user=user,
            role=GroupMembership.ROLE_MEMBER,
        )

        # Clear recorded writes
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Delete membership
        membership.delete()

        delete_tuples = {
            (d.object, d.relation, d.subject)
            for d in rebac_setup.deletes
        }

        assert (
            f"group:{group.pk}",
            "member",
            f"user:{user.pk}",
        ) in delete_tuples

    def test_membership_group_change_deletes_old_tuple(self, rebac_setup):
        """Changing group should delete old tuple and create new one."""
        user = User.objects.create_user(username="user", password="pass")
        group_a = Group.objects.create(name="GroupA", slug="groupa")
        group_b = Group.objects.create(name="GroupB", slug="groupb")

        # Create membership in group A
        membership = GroupMembership.objects.create(
            group=group_a,
            user=user,
            role=GroupMembership.ROLE_MEMBER,
        )

        # Clear recorded writes
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Move to group B
        membership.group = group_b
        membership.save()

        # Check old tuple deleted
        delete_tuples = {
            (d.object, d.relation, d.subject)
            for d in rebac_setup.deletes
        }
        assert (
            f"group:{group_a.pk}",
            "member",
            f"user:{user.pk}",
        ) in delete_tuples

        # Check new tuple written
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (
            f"group:{group_b.pk}",
            "member",
            f"user:{user.pk}",
        ) in write_tuples

    def test_membership_user_change_deletes_old_tuple(self, rebac_setup):
        """Changing user should delete old tuple and create new one."""
        user_a = User.objects.create_user(username="usera", password="pass")
        user_b = User.objects.create_user(username="userb", password="pass")
        group = Group.objects.create(name="Group", slug="group")

        # Create membership for user A
        membership = GroupMembership.objects.create(
            group=group,
            user=user_a,
            role=GroupMembership.ROLE_MEMBER,
        )

        # Clear recorded writes
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change to user B
        membership.user = user_b
        membership.save()

        # Check old tuple deleted
        delete_tuples = {
            (d.object, d.relation, d.subject)
            for d in rebac_setup.deletes
        }
        assert (
            f"group:{group.pk}",
            "member",
            f"user:{user_a.pk}",
        ) in delete_tuples

        # Check new tuple written
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (
            f"group:{group.pk}",
            "member",
            f"user:{user_b.pk}",
        ) in write_tuples

    def test_membership_no_change_skips_write(self, rebac_setup):
        """Saving without changes should not write duplicate tuples."""
        user = User.objects.create_user(username="user", password="pass")
        group = Group.objects.create(name="Group", slug="group")

        membership = GroupMembership.objects.create(
            group=group,
            user=user,
            role=GroupMembership.ROLE_MEMBER,
        )

        # Clear recorded writes
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Save without changes
        membership.save()

        # Should not write new tuples or delete anything
        assert len(rebac_setup.writes) == 0
        assert len(rebac_setup.deletes) == 0
