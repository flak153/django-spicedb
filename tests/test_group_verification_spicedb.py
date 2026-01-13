"""
Integration tests for Group/Verification pattern with real SpiceDB.

These tests verify the full end-to-end flow:
1. Schema publishes correctly
2. Tuples are written for group membership
3. Permission inheritance works through group->verification
4. Reverse lookup (lookup_subjects) works
"""

import pytest
from django.contrib.auth import get_user_model

import django_rebac.conf as conf
from django_rebac.adapters.base import TupleKey, TupleWrite

from example_project.documents.models import Group, GroupMembership, Verification


User = get_user_model()

# Use fully_consistent for all checks to avoid eventual consistency issues
CONSISTENCY = "fully_consistent"


@pytest.fixture
def clean_spicedb(spicedb_adapter):
    """Ensure SpiceDB is clean before each test."""
    # Publish schema
    graph = conf.get_type_graph()
    schema = graph.compile_schema()
    spicedb_adapter.publish_schema(schema)

    yield spicedb_adapter

    # Cleanup
    try:
        spicedb_adapter.delete_all_relationships("verification")
    except Exception:
        pass
    try:
        spicedb_adapter.delete_all_relationships("group")
    except Exception:
        pass


@pytest.mark.django_db
class TestSchemaPublishing:
    """Test schema publishes correctly with Group/Verification."""

    def test_schema_compiles_with_group_and_verification(self, clean_spicedb):
        """Schema should include both group and verification definitions."""
        graph = conf.get_type_graph()
        schema = graph.compile_schema()

        # Verify both types are in schema
        assert "definition group" in schema
        assert "definition verification" in schema

        # Verify group relations
        assert "relation member: user" in schema
        assert "relation manager: user" in schema

        # Verify verification relations
        assert "relation owner: user" in schema
        assert "relation parent: group" in schema


@pytest.mark.django_db
class TestGroupMembershipPermissions:
    """Test group membership creates correct permissions."""

    def test_group_member_has_view_permission(self, clean_spicedb):
        """User with member relation on group should have view permission."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="group:1",
                relation="member",
                subject="user:1",
            ))
        ])

        assert clean_spicedb.check(
            subject="user:1",
            relation="view",
            object_="group:1",
            consistency=CONSISTENCY,
        )

    def test_group_member_cannot_manage(self, clean_spicedb):
        """Member should not have manage permission (only managers)."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="group:1",
                relation="member",
                subject="user:1",
            ))
        ])

        assert not clean_spicedb.check(
            subject="user:1",
            relation="manage",
            object_="group:1",
            consistency=CONSISTENCY,
        )

    def test_group_manager_has_view_and_manage(self, clean_spicedb):
        """Manager should have both view and manage permissions."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="group:1",
                relation="manager",
                subject="user:2",
            ))
        ])

        assert clean_spicedb.check(
            subject="user:2",
            relation="view",
            object_="group:1",
            consistency=CONSISTENCY,
        )

        assert clean_spicedb.check(
            subject="user:2",
            relation="manage",
            object_="group:1",
            consistency=CONSISTENCY,
        )


@pytest.mark.django_db
class TestVerificationPermissionInheritance:
    """Test verification inherits permissions from parent group."""

    def test_owner_can_view_and_manage(self, clean_spicedb):
        """Owner always has full access."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="owner",
                subject="user:1",
            )),
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="parent",
                subject="group:1",
            )),
        ])

        assert clean_spicedb.check("user:1", "view", "verification:1", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:1", "manage", "verification:1", consistency=CONSISTENCY)

    def test_group_member_can_view_verification(self, clean_spicedb):
        """Group member can view verification via parent->view."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="group:1",
                relation="member",
                subject="user:2",
            )),
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="parent",
                subject="group:1",
            )),
        ])

        assert clean_spicedb.check("user:2", "view", "verification:1", consistency=CONSISTENCY)

    def test_group_member_cannot_manage_verification(self, clean_spicedb):
        """Group member cannot manage verification (only managers can)."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="group:1",
                relation="member",
                subject="user:2",
            )),
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="parent",
                subject="group:1",
            )),
        ])

        assert not clean_spicedb.check("user:2", "manage", "verification:1", consistency=CONSISTENCY)

    def test_group_manager_can_view_and_manage_verification(self, clean_spicedb):
        """Group manager can view and manage verification via parent->manage."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="group:1",
                relation="manager",
                subject="user:3",
            )),
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="parent",
                subject="group:1",
            )),
        ])

        assert clean_spicedb.check("user:3", "view", "verification:1", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:3", "manage", "verification:1", consistency=CONSISTENCY)

    def test_non_member_cannot_access_verification(self, clean_spicedb):
        """User not in group cannot access verification."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="parent",
                subject="group:1",
            )),
        ])

        assert not clean_spicedb.check("user:99", "view", "verification:1", consistency=CONSISTENCY)
        assert not clean_spicedb.check("user:99", "manage", "verification:1", consistency=CONSISTENCY)


@pytest.mark.django_db
class TestLookupSubjects:
    """Test reverse lookup - who can access a verification?"""

    def test_lookup_subjects_returns_owner(self, clean_spicedb):
        """lookup_subjects should return the owner."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="owner",
                subject="user:1",
            )),
            TupleWrite(key=TupleKey(
                object="verification:1",
                relation="parent",
                subject="group:1",
            )),
        ])

        subjects = list(clean_spicedb.lookup_subjects(
            resource="verification:1",
            permission="view",
            subject_type="user",
            consistency=CONSISTENCY,
        ))

        assert "1" in subjects

    def test_lookup_subjects_returns_group_members(self, clean_spicedb):
        """lookup_subjects should return group members."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(object="group:1", relation="member", subject="user:10")),
            TupleWrite(key=TupleKey(object="group:1", relation="member", subject="user:11")),
            TupleWrite(key=TupleKey(object="verification:1", relation="parent", subject="group:1")),
        ])

        subjects = list(clean_spicedb.lookup_subjects(
            resource="verification:1",
            permission="view",
            subject_type="user",
            consistency=CONSISTENCY,
        ))

        assert "10" in subjects
        assert "11" in subjects

    def test_lookup_subjects_returns_group_manager(self, clean_spicedb):
        """lookup_subjects should return group managers."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(object="group:1", relation="manager", subject="user:20")),
            TupleWrite(key=TupleKey(object="verification:1", relation="parent", subject="group:1")),
        ])

        subjects = list(clean_spicedb.lookup_subjects(
            resource="verification:1",
            permission="manage",
            subject_type="user",
            consistency=CONSISTENCY,
        ))

        assert "20" in subjects


@pytest.mark.django_db
class TestLookupResources:
    """Test forward lookup - what can a user access?"""

    def test_lookup_resources_returns_owned_verifications(self, clean_spicedb):
        """lookup_resources should return verifications user owns."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(object="verification:1", relation="owner", subject="user:1")),
            TupleWrite(key=TupleKey(object="verification:2", relation="owner", subject="user:1")),
            TupleWrite(key=TupleKey(object="verification:1", relation="parent", subject="group:1")),
            TupleWrite(key=TupleKey(object="verification:2", relation="parent", subject="group:1")),
        ])

        resources = list(clean_spicedb.lookup_resources(
            subject="user:1",
            relation="view",
            resource_type="verification",
            consistency=CONSISTENCY,
        ))

        assert "1" in resources
        assert "2" in resources

    def test_lookup_resources_returns_group_verifications(self, clean_spicedb):
        """lookup_resources should return verifications from user's group."""
        clean_spicedb.write_tuples([
            TupleWrite(key=TupleKey(object="group:1", relation="member", subject="user:5")),
            TupleWrite(key=TupleKey(object="verification:10", relation="parent", subject="group:1")),
            TupleWrite(key=TupleKey(object="verification:11", relation="parent", subject="group:1")),
            TupleWrite(key=TupleKey(object="verification:99", relation="parent", subject="group:2")),
        ])

        resources = list(clean_spicedb.lookup_resources(
            subject="user:5",
            relation="view",
            resource_type="verification",
            consistency=CONSISTENCY,
        ))

        assert "10" in resources
        assert "11" in resources
        assert "99" not in resources


@pytest.mark.django_db
class TestFullScenario:
    """Test a complete real-world scenario."""

    def test_verify4_scenario(self, clean_spicedb):
        """
        Simulate Verify4 use case:
        - Engineering team with 2 members and 1 manager
        - 3 verifications belonging to the team
        - Members can view all, manager can manage all
        """
        clean_spicedb.write_tuples([
            # Engineering team members
            TupleWrite(key=TupleKey(object="group:eng", relation="member", subject="user:alice")),
            TupleWrite(key=TupleKey(object="group:eng", relation="member", subject="user:bob")),
            # Engineering team manager
            TupleWrite(key=TupleKey(object="group:eng", relation="manager", subject="user:charlie")),
            # Verifications in Engineering
            TupleWrite(key=TupleKey(object="verification:v1", relation="owner", subject="user:alice")),
            TupleWrite(key=TupleKey(object="verification:v1", relation="parent", subject="group:eng")),
            TupleWrite(key=TupleKey(object="verification:v2", relation="owner", subject="user:bob")),
            TupleWrite(key=TupleKey(object="verification:v2", relation="parent", subject="group:eng")),
            TupleWrite(key=TupleKey(object="verification:v3", relation="owner", subject="user:alice")),
            TupleWrite(key=TupleKey(object="verification:v3", relation="parent", subject="group:eng")),
        ])

        # Alice can view all verifications (member + owner of v1, v3)
        assert clean_spicedb.check("user:alice", "view", "verification:v1", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:alice", "view", "verification:v2", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:alice", "view", "verification:v3", consistency=CONSISTENCY)

        # Alice can only manage her own verifications
        assert clean_spicedb.check("user:alice", "manage", "verification:v1", consistency=CONSISTENCY)
        assert not clean_spicedb.check("user:alice", "manage", "verification:v2", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:alice", "manage", "verification:v3", consistency=CONSISTENCY)

        # Bob can view all, manage only his own
        assert clean_spicedb.check("user:bob", "view", "verification:v1", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:bob", "view", "verification:v2", consistency=CONSISTENCY)
        assert not clean_spicedb.check("user:bob", "manage", "verification:v1", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:bob", "manage", "verification:v2", consistency=CONSISTENCY)

        # Charlie (manager) can view and manage ALL
        assert clean_spicedb.check("user:charlie", "view", "verification:v1", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:charlie", "view", "verification:v2", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:charlie", "view", "verification:v3", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:charlie", "manage", "verification:v1", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:charlie", "manage", "verification:v2", consistency=CONSISTENCY)
        assert clean_spicedb.check("user:charlie", "manage", "verification:v3", consistency=CONSISTENCY)

        # Outsider can't access anything
        assert not clean_spicedb.check("user:outsider", "view", "verification:v1", consistency=CONSISTENCY)
        assert not clean_spicedb.check("user:outsider", "manage", "verification:v1", consistency=CONSISTENCY)

        # Reverse lookup: who can view v1?
        viewers = list(clean_spicedb.lookup_subjects(
            resource="verification:v1",
            permission="view",
            subject_type="user",
            consistency=CONSISTENCY,
        ))
        assert "alice" in viewers
        assert "bob" in viewers
        assert "charlie" in viewers

        # Reverse lookup: who can manage v1?
        managers = list(clean_spicedb.lookup_subjects(
            resource="verification:v1",
            permission="manage",
            subject_type="user",
            consistency=CONSISTENCY,
        ))
        assert "alice" in managers
        assert "bob" not in managers
        assert "charlie" in managers


@pytest.mark.django_db(transaction=True)
class TestDjangoModelIntegration:
    """Test that Django model operations sync tuples to SpiceDB."""

    def test_group_membership_creates_tuple(self, spicedb_adapter):
        """Creating GroupMembership via Django should sync tuple to SpiceDB."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        # Publish schema
        graph = conf.get_type_graph()
        schema = graph.compile_schema()
        spicedb_adapter.publish_schema(schema)

        try:
            user = User.objects.create_user(username="testmember", password="pass")
            group = Group.objects.create(name="TestGroup", slug="testgroup")

            # Create membership
            membership = GroupMembership.objects.create(
                group=group,
                user=user,
                role=GroupMembership.ROLE_MEMBER,
            )

            # Verify tuple was written to SpiceDB
            assert spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="view",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )

            # Member should not have manage permission
            assert not spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="manage",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )
        finally:
            factory.reset_adapter()

    def test_manager_membership_creates_tuple(self, spicedb_adapter):
        """Creating manager GroupMembership should grant manage permission."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        schema = graph.compile_schema()
        spicedb_adapter.publish_schema(schema)

        try:
            user = User.objects.create_user(username="testmanager", password="pass")
            group = Group.objects.create(name="TestGroup2", slug="testgroup2")

            # Create manager membership
            membership = GroupMembership.objects.create(
                group=group,
                user=user,
                role=GroupMembership.ROLE_MANAGER,
            )

            # Manager should have both view and manage
            assert spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="view",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )
            assert spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="manage",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )
        finally:
            factory.reset_adapter()

    def test_role_change_updates_permissions(self, spicedb_adapter):
        """Changing role from member to manager should update SpiceDB."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        schema = graph.compile_schema()
        spicedb_adapter.publish_schema(schema)

        try:
            user = User.objects.create_user(username="promoteduser", password="pass")
            group = Group.objects.create(name="TestGroup3", slug="testgroup3")

            # Start as member
            membership = GroupMembership.objects.create(
                group=group,
                user=user,
                role=GroupMembership.ROLE_MEMBER,
            )

            # Initially can view but not manage
            assert spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="view",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )
            assert not spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="manage",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )

            # Promote to manager
            membership.role = GroupMembership.ROLE_MANAGER
            membership.save()

            # Now should have manage permission
            assert spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="manage",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )
        finally:
            factory.reset_adapter()

    def test_membership_delete_revokes_permissions(self, spicedb_adapter):
        """Deleting GroupMembership should revoke permissions in SpiceDB."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        schema = graph.compile_schema()
        spicedb_adapter.publish_schema(schema)

        try:
            user = User.objects.create_user(username="removeduser", password="pass")
            group = Group.objects.create(name="TestGroup4", slug="testgroup4")

            membership = GroupMembership.objects.create(
                group=group,
                user=user,
                role=GroupMembership.ROLE_MEMBER,
            )

            # Verify access
            assert spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="view",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )

            # Delete membership
            membership.delete()

            # Access should be revoked
            assert not spicedb_adapter.check(
                subject=f"user:{user.pk}",
                relation="view",
                object_=f"group:{group.pk}",
                consistency=CONSISTENCY,
            )
        finally:
            factory.reset_adapter()

    def test_verification_inherits_from_group_via_django(self, spicedb_adapter):
        """Creating Verification via Django should inherit group permissions."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        schema = graph.compile_schema()
        spicedb_adapter.publish_schema(schema)

        try:
            owner = User.objects.create_user(username="vowner", password="pass")
            member = User.objects.create_user(username="vmember", password="pass")
            manager = User.objects.create_user(username="vmanager", password="pass")
            outsider = User.objects.create_user(username="vout", password="pass")

            group = Group.objects.create(name="VerifyGroup", slug="verifygroup")

            # Add memberships
            GroupMembership.objects.create(group=group, user=member, role=GroupMembership.ROLE_MEMBER)
            GroupMembership.objects.create(group=group, user=manager, role=GroupMembership.ROLE_MANAGER)

            # Create verification
            verification = Verification.objects.create(
                title="Test Verification",
                owner=owner,
                group=group,
            )

            # Owner can view and manage
            assert spicedb_adapter.check(
                f"user:{owner.pk}", "view", f"verification:{verification.pk}",
                consistency=CONSISTENCY,
            )
            assert spicedb_adapter.check(
                f"user:{owner.pk}", "manage", f"verification:{verification.pk}",
                consistency=CONSISTENCY,
            )

            # Member can view but not manage
            assert spicedb_adapter.check(
                f"user:{member.pk}", "view", f"verification:{verification.pk}",
                consistency=CONSISTENCY,
            )
            assert not spicedb_adapter.check(
                f"user:{member.pk}", "manage", f"verification:{verification.pk}",
                consistency=CONSISTENCY,
            )

            # Manager can view and manage
            assert spicedb_adapter.check(
                f"user:{manager.pk}", "view", f"verification:{verification.pk}",
                consistency=CONSISTENCY,
            )
            assert spicedb_adapter.check(
                f"user:{manager.pk}", "manage", f"verification:{verification.pk}",
                consistency=CONSISTENCY,
            )

            # Outsider cannot access
            assert not spicedb_adapter.check(
                f"user:{outsider.pk}", "view", f"verification:{verification.pk}",
                consistency=CONSISTENCY,
            )
        finally:
            factory.reset_adapter()


@pytest.mark.django_db(transaction=True)
class TestMultiGroupScenarios:
    """Test complex scenarios with multiple groups."""

    def test_user_in_multiple_groups_different_roles(self, spicedb_adapter):
        """User can be member in one group, manager in another."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        spicedb_adapter.publish_schema(graph.compile_schema())

        try:
            user = User.objects.create_user(username="multiuser", password="pass")
            owner = User.objects.create_user(username="owner", password="pass")

            group_a = Group.objects.create(name="GroupA", slug="groupa")
            group_b = Group.objects.create(name="GroupB", slug="groupb")

            # User is member in A, manager in B
            GroupMembership.objects.create(group=group_a, user=user, role=GroupMembership.ROLE_MEMBER)
            GroupMembership.objects.create(group=group_b, user=user, role=GroupMembership.ROLE_MANAGER)

            # Create verifications in each group
            v_a = Verification.objects.create(title="VerifyA", owner=owner, group=group_a)
            v_b = Verification.objects.create(title="VerifyB", owner=owner, group=group_b)

            # User can view both
            assert spicedb_adapter.check(f"user:{user.pk}", "view", f"verification:{v_a.pk}", consistency=CONSISTENCY)
            assert spicedb_adapter.check(f"user:{user.pk}", "view", f"verification:{v_b.pk}", consistency=CONSISTENCY)

            # User can only manage B (where they're manager)
            assert not spicedb_adapter.check(f"user:{user.pk}", "manage", f"verification:{v_a.pk}", consistency=CONSISTENCY)
            assert spicedb_adapter.check(f"user:{user.pk}", "manage", f"verification:{v_b.pk}", consistency=CONSISTENCY)
        finally:
            factory.reset_adapter()

    def test_verification_group_change(self, spicedb_adapter):
        """Moving verification to different group should update permissions."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        spicedb_adapter.publish_schema(graph.compile_schema())

        try:
            owner = User.objects.create_user(username="moveowner", password="pass")
            user_a = User.objects.create_user(username="usera", password="pass")
            user_b = User.objects.create_user(username="userb", password="pass")

            group_a = Group.objects.create(name="GroupMoveA", slug="groupmovea")
            group_b = Group.objects.create(name="GroupMoveB", slug="groupmoveb")

            GroupMembership.objects.create(group=group_a, user=user_a, role=GroupMembership.ROLE_MEMBER)
            GroupMembership.objects.create(group=group_b, user=user_b, role=GroupMembership.ROLE_MEMBER)

            # Create verification in group A
            verification = Verification.objects.create(title="MovableVerify", owner=owner, group=group_a)

            # User A can view, User B cannot
            assert spicedb_adapter.check(f"user:{user_a.pk}", "view", f"verification:{verification.pk}", consistency=CONSISTENCY)
            assert not spicedb_adapter.check(f"user:{user_b.pk}", "view", f"verification:{verification.pk}", consistency=CONSISTENCY)

            # Move to group B
            verification.group = group_b
            verification.save()

            # Now User B can view, User A cannot
            assert not spicedb_adapter.check(f"user:{user_a.pk}", "view", f"verification:{verification.pk}", consistency=CONSISTENCY)
            assert spicedb_adapter.check(f"user:{user_b.pk}", "view", f"verification:{verification.pk}", consistency=CONSISTENCY)
        finally:
            factory.reset_adapter()

    def test_lookup_resources_across_groups(self, spicedb_adapter):
        """lookup_resources should return verifications from all user's groups."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        spicedb_adapter.publish_schema(graph.compile_schema())

        try:
            user = User.objects.create_user(username="lookupuser", password="pass")
            owner = User.objects.create_user(username="lookupowner", password="pass")

            group_1 = Group.objects.create(name="LookupGroup1", slug="lookupgroup1")
            group_2 = Group.objects.create(name="LookupGroup2", slug="lookupgroup2")
            group_3 = Group.objects.create(name="LookupGroup3", slug="lookupgroup3")

            # User is in groups 1 and 2, not 3
            GroupMembership.objects.create(group=group_1, user=user, role=GroupMembership.ROLE_MEMBER)
            GroupMembership.objects.create(group=group_2, user=user, role=GroupMembership.ROLE_MEMBER)

            v1 = Verification.objects.create(title="V1", owner=owner, group=group_1)
            v2 = Verification.objects.create(title="V2", owner=owner, group=group_2)
            v3 = Verification.objects.create(title="V3", owner=owner, group=group_3)

            # Lookup should return v1 and v2, not v3
            resources = list(spicedb_adapter.lookup_resources(
                subject=f"user:{user.pk}",
                relation="view",
                resource_type="verification",
                consistency=CONSISTENCY,
            ))

            assert str(v1.pk) in resources
            assert str(v2.pk) in resources
            assert str(v3.pk) not in resources
        finally:
            factory.reset_adapter()


@pytest.mark.django_db(transaction=True)
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_group_no_access(self, spicedb_adapter):
        """Verification in empty group should only be accessible by owner."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        spicedb_adapter.publish_schema(graph.compile_schema())

        try:
            owner = User.objects.create_user(username="emptyowner", password="pass")
            stranger = User.objects.create_user(username="stranger", password="pass")

            group = Group.objects.create(name="EmptyGroup", slug="emptygroup")
            # No memberships added

            verification = Verification.objects.create(title="LonelyVerify", owner=owner, group=group)

            # Owner can access
            assert spicedb_adapter.check(f"user:{owner.pk}", "view", f"verification:{verification.pk}", consistency=CONSISTENCY)

            # Stranger cannot
            assert not spicedb_adapter.check(f"user:{stranger.pk}", "view", f"verification:{verification.pk}", consistency=CONSISTENCY)
        finally:
            factory.reset_adapter()

    def test_demote_manager_to_member(self, spicedb_adapter):
        """Demoting manager to member should revoke manage permission."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        spicedb_adapter.publish_schema(graph.compile_schema())

        try:
            user = User.objects.create_user(username="demoteduser", password="pass")
            owner = User.objects.create_user(username="demoteowner", password="pass")

            group = Group.objects.create(name="DemoteGroup", slug="demotegroup")
            membership = GroupMembership.objects.create(group=group, user=user, role=GroupMembership.ROLE_MANAGER)

            verification = Verification.objects.create(title="DemoteVerify", owner=owner, group=group)

            # Initially can manage
            assert spicedb_adapter.check(f"user:{user.pk}", "manage", f"verification:{verification.pk}", consistency=CONSISTENCY)

            # Demote to member
            membership.role = GroupMembership.ROLE_MEMBER
            membership.save()

            # Can still view but not manage
            assert spicedb_adapter.check(f"user:{user.pk}", "view", f"verification:{verification.pk}", consistency=CONSISTENCY)
            assert not spicedb_adapter.check(f"user:{user.pk}", "manage", f"verification:{verification.pk}", consistency=CONSISTENCY)
        finally:
            factory.reset_adapter()

    def test_verification_owner_change(self, spicedb_adapter):
        """Changing verification owner should update permissions."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        spicedb_adapter.publish_schema(graph.compile_schema())

        try:
            owner1 = User.objects.create_user(username="owner1", password="pass")
            owner2 = User.objects.create_user(username="owner2", password="pass")

            group = Group.objects.create(name="OwnerChangeGroup", slug="ownerchangegroup")

            verification = Verification.objects.create(title="OwnerChangeVerify", owner=owner1, group=group)

            # Owner1 can manage
            assert spicedb_adapter.check(f"user:{owner1.pk}", "manage", f"verification:{verification.pk}", consistency=CONSISTENCY)
            assert not spicedb_adapter.check(f"user:{owner2.pk}", "manage", f"verification:{verification.pk}", consistency=CONSISTENCY)

            # Transfer ownership
            verification.owner = owner2
            verification.save()

            # Now owner2 can manage, owner1 cannot
            assert not spicedb_adapter.check(f"user:{owner1.pk}", "manage", f"verification:{verification.pk}", consistency=CONSISTENCY)
            assert spicedb_adapter.check(f"user:{owner2.pk}", "manage", f"verification:{verification.pk}", consistency=CONSISTENCY)
        finally:
            factory.reset_adapter()

    def test_bulk_membership_operations(self, spicedb_adapter):
        """Test adding multiple users to group."""
        from django_rebac.adapters import factory
        from django_rebac.sync import registry
        import django_rebac.conf as conf

        factory.set_adapter(spicedb_adapter)
        conf.reset_type_graph_cache()
        registry.refresh()

        graph = conf.get_type_graph()
        spicedb_adapter.publish_schema(graph.compile_schema())

        try:
            owner = User.objects.create_user(username="bulkowner", password="pass")
            users = [User.objects.create_user(username=f"bulkuser{i}", password="pass") for i in range(5)]

            group = Group.objects.create(name="BulkGroup", slug="bulkgroup")

            # Add all users as members
            for user in users:
                GroupMembership.objects.create(group=group, user=user, role=GroupMembership.ROLE_MEMBER)

            verification = Verification.objects.create(title="BulkVerify", owner=owner, group=group)

            # All users should be able to view
            for user in users:
                assert spicedb_adapter.check(
                    f"user:{user.pk}", "view", f"verification:{verification.pk}",
                    consistency=CONSISTENCY,
                ), f"User {user.username} should be able to view"

            # Lookup subjects should return all users
            viewers = list(spicedb_adapter.lookup_subjects(
                resource=f"verification:{verification.pk}",
                permission="view",
                subject_type="user",
                consistency=CONSISTENCY,
            ))

            for user in users:
                assert str(user.pk) in viewers, f"User {user.pk} should be in viewers"
        finally:
            factory.reset_adapter()
