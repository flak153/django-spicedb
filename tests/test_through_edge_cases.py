"""Edge case tests for through-table binding support."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

import django_spicedb.conf as conf
from django_spicedb.core import build_type_configs_from_registry
from django_spicedb.sync import registry
from django_spicedb.sync.backfill import generate_through_tuples

from example_project.documents.models import Group, GroupMembership


User = get_user_model()


@pytest.fixture
def rebac_setup(recording_adapter):
    """Setup fixture for through-binding edge case tests."""
    conf.reset_type_graph_cache()
    registry.refresh()
    yield recording_adapter
    conf.reset_type_graph_cache()
    registry.refresh()


@pytest.mark.django_db(transaction=True)
class TestSubjectFKChange:
    """Test changing the subject FK on a through table."""

    def test_subject_fk_change_deletes_old_writes_new(self, rebac_setup):
        """Changing user FK on GroupMembership should delete old tuple, write new one."""
        user_a = User.objects.create_user(username="subj_fk_a", password="pass")
        user_b = User.objects.create_user(username="subj_fk_b", password="pass")
        group = Group.objects.create(name="SubjFKGroup", slug="subjfkgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change the user FK
        membership.user = user_b
        membership.save()

        # Should delete the old tuple
        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "member", f"user:{user_a.pk}") in delete_tuples

        # Should write the new tuple
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "member", f"user:{user_b.pk}") in write_tuples

    def test_subject_fk_change_with_manager_role(self, rebac_setup):
        """Changing user on manager membership should update correctly."""
        user_x = User.objects.create_user(username="subj_mgr_x", password="pass")
        user_y = User.objects.create_user(username="subj_mgr_y", password="pass")
        group = Group.objects.create(name="SubjMgrGroup", slug="subjmgrgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user_x, role=GroupMembership.ROLE_MANAGER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        membership.user = user_y
        membership.save()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "manager", f"user:{user_x.pk}") in delete_tuples

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "manager", f"user:{user_y.pk}") in write_tuples


@pytest.mark.django_db(transaction=True)
class TestSimultaneousRoleAndFKChange:
    """Test changing both role and FK in the same save."""

    def test_role_and_user_change_together(self, rebac_setup):
        """Changing both role and user in one save should delete old, write new."""
        user_a = User.objects.create_user(username="both_a", password="pass")
        user_b = User.objects.create_user(username="both_b", password="pass")
        group = Group.objects.create(name="BothGroup", slug="bothgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change both role and user
        membership.user = user_b
        membership.role = GroupMembership.ROLE_MANAGER
        membership.save()

        # Should delete old (member, user_a)
        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "member", f"user:{user_a.pk}") in delete_tuples

        # Should write new (manager, user_b)
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "manager", f"user:{user_b.pk}") in write_tuples

    def test_role_and_group_change_together(self, rebac_setup):
        """Changing both role and group in one save."""
        user = User.objects.create_user(username="role_grp_user", password="pass")
        group_a = Group.objects.create(name="RoleGrpA", slug="rolegrpa")
        group_b = Group.objects.create(name="RoleGrpB", slug="rolegrpb")

        membership = GroupMembership.objects.create(
            group=group_a, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change both group and role
        membership.group = group_b
        membership.role = GroupMembership.ROLE_MANAGER
        membership.save()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        # Old: (group_a, member, user)
        assert (f"group:{group_a.pk}", "member", f"user:{user.pk}") in delete_tuples

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        # New: (group_b, manager, user)
        assert (f"group:{group_b.pk}", "manager", f"user:{user.pk}") in write_tuples

    def test_all_three_fields_change(self, rebac_setup):
        """Changing group, user, and role all at once."""
        user_a = User.objects.create_user(username="all3_a", password="pass")
        user_b = User.objects.create_user(username="all3_b", password="pass")
        group_a = Group.objects.create(name="All3A", slug="all3a")
        group_b = Group.objects.create(name="All3B", slug="all3b")

        membership = GroupMembership.objects.create(
            group=group_a, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change all three
        membership.group = group_b
        membership.user = user_b
        membership.role = GroupMembership.ROLE_MANAGER
        membership.save()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group_a.pk}", "member", f"user:{user_a.pk}") in delete_tuples

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group_b.pk}", "manager", f"user:{user_b.pk}") in write_tuples


@pytest.mark.django_db(transaction=True)
class TestUnknownRoleValue:
    """Test through-table with role values not in role_mapping.

    This documents the current behavior: unknown role values are silently skipped.
    """

    def test_unknown_role_value_on_create(self, rebac_setup):
        """Creating a membership with unknown role value should not write tuple."""
        user = User.objects.create_user(username="unknown_role", password="pass")
        group = Group.objects.create(name="UnknownRoleGroup", slug="unknownrolegroup")

        # Bypass model validation to force an unknown role
        membership = GroupMembership(
            group=group, user=user, role="unknown_role"
        )
        # Bypass Django validation
        membership._meta.get_field("role").null = True
        membership.save()

        # Should not have written any tuples for this role
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        # No tuple should exist for unknown_role since it's not in role_mapping
        member_writes = [
            t for t in write_tuples
            if t[0] == f"group:{group.pk}" and t[1] == "member"
        ]
        manager_writes = [
            t for t in write_tuples
            if t[0] == f"group:{group.pk}" and t[1] == "manager"
        ]
        assert len(member_writes) == 0
        assert len(manager_writes) == 0

    def test_unknown_role_value_on_update(self, rebac_setup):
        """Changing to unknown role value should delete old tuple."""
        user = User.objects.create_user(username="unknown_upd", password="pass")
        group = Group.objects.create(name="UnknownUpdGroup", slug="unknownupdgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change to unknown role
        membership.role = "unknown_role"
        membership._meta.get_field("role").null = True
        membership.save()

        # Should delete the old tuple
        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "member", f"user:{user.pk}") in delete_tuples

        # Should not write a new tuple
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        unknown_writes = [
            t for t in write_tuples
            if t[0] == f"group:{group.pk}" and t[2] == f"user:{user.pk}"
        ]
        # Only old deletes, no new writes
        assert len(unknown_writes) == 0


@pytest.mark.django_db(transaction=True)
class TestCascadingDeletesThroughTable:
    """Test cascading deletes through the through table."""

    def test_delete_group_removes_membership_tuples(self, rebac_setup):
        """Deleting a group should cascade-delete memberships and their tuples."""
        user_a = User.objects.create_user(username="cascade_a", password="pass")
        user_b = User.objects.create_user(username="cascade_b", password="pass")
        group = Group.objects.create(name="CascadeGroup", slug="cascadegroup")
        group_pk = group.pk  # Save before delete

        GroupMembership.objects.create(
            group=group, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_b, role=GroupMembership.ROLE_MANAGER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Delete the group (cascade to memberships)
        group.delete()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        # Both membership tuples should be deleted
        assert (f"group:{group_pk}", "member", f"user:{user_a.pk}") in delete_tuples
        assert (f"group:{group_pk}", "manager", f"user:{user_b.pk}") in delete_tuples

    def test_delete_user_removes_membership_tuples(self, rebac_setup):
        """Deleting a user should cascade-delete their memberships."""
        user = User.objects.create_user(username="del_user", password="pass")
        group_a = Group.objects.create(name="DelUserA", slug="delusera")
        group_b = Group.objects.create(name="DelUserB", slug="deluserb")

        mem_a = GroupMembership.objects.create(
            group=group_a, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        mem_b = GroupMembership.objects.create(
            group=group_b, user=user, role=GroupMembership.ROLE_MANAGER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Delete the user
        user.delete()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group_a.pk}", "member", f"user:{mem_a.user_id}") in delete_tuples
        assert (f"group:{group_b.pk}", "manager", f"user:{mem_b.user_id}") in delete_tuples


@pytest.mark.django_db(transaction=True)
class TestBulkThroughTableOperations:
    """Test bulk operations (bulk_create, queryset delete) on through tables.

    These test the current behavior:
    - bulk_create does not trigger post_save signals (Django limitation)
    - queryset.delete() DOES trigger post_delete signals per row (Django 4.2+)
    """

    def test_bulk_create_membership_writes_tuples(self, rebac_setup):
        """bulk_create on GroupMembership writes tuples via RebacThroughManager."""
        user_a = User.objects.create_user(username="bulk_a", password="pass")
        user_b = User.objects.create_user(username="bulk_b", password="pass")
        group = Group.objects.create(name="BulkGroup", slug="bulkgroup")

        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Bulk create memberships
        GroupMembership.objects.bulk_create([
            GroupMembership(group=group, user=user_a, role=GroupMembership.ROLE_MEMBER),
            GroupMembership(group=group, user=user_b, role=GroupMembership.ROLE_MANAGER),
        ])

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "member", f"user:{user_a.pk}") in write_tuples
        assert (f"group:{group.pk}", "manager", f"user:{user_b.pk}") in write_tuples

    def test_queryset_delete_membership_removes_tuples(self, rebac_setup):
        """Bulk delete via queryset should remove membership tuples."""
        user_a = User.objects.create_user(username="qs_del_a", password="pass")
        user_b = User.objects.create_user(username="qs_del_b", password="pass")
        group = Group.objects.create(name="QSDelGroup", slug="qsdelgroup")

        GroupMembership.objects.create(
            group=group, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_b, role=GroupMembership.ROLE_MANAGER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Delete via queryset
        GroupMembership.objects.filter(group=group).delete()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "member", f"user:{user_a.pk}") in delete_tuples
        assert (f"group:{group.pk}", "manager", f"user:{user_b.pk}") in delete_tuples

    def test_single_row_delete_in_loop_works(self, rebac_setup):
        """Deleting rows one-by-one in a loop should work."""
        user_a = User.objects.create_user(username="loop_del_a", password="pass")
        user_b = User.objects.create_user(username="loop_del_b", password="pass")
        group = Group.objects.create(name="LoopDelGroup", slug="loopdelgroup")

        GroupMembership.objects.create(
            group=group, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_b, role=GroupMembership.ROLE_MANAGER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Delete one by one
        for membership in GroupMembership.objects.filter(group=group):
            membership.delete()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "member", f"user:{user_a.pk}") in delete_tuples
        assert (f"group:{group.pk}", "manager", f"user:{user_b.pk}") in delete_tuples


@pytest.mark.django_db
class TestThroughTableBackfillEdgeCases:
    """Test backfill with edge cases like NULL FKs and deleted objects."""

    def test_backfill_with_valid_memberships(self):
        """Backfill should generate tuples for valid memberships."""
        user_a = User.objects.create_user(username="bf_valid_a", password="pass")
        user_b = User.objects.create_user(username="bf_valid_b", password="pass")
        group = Group.objects.create(name="BFValidGroup", slug="bfvalidgroup")

        GroupMembership.objects.create(
            group=group, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_b, role=GroupMembership.ROLE_MANAGER,
        )

        configs = build_type_configs_from_registry()
        tuples = list(generate_through_tuples("group", configs["group"]))

        tuples_set = {
            (t.key.object, t.key.relation, t.key.subject) for t in tuples
        }
        assert (f"group:{group.pk}", "member", f"user:{user_a.pk}") in tuples_set
        assert (f"group:{group.pk}", "manager", f"user:{user_b.pk}") in tuples_set

    def test_backfill_filters_by_role(self):
        """Backfill should only generate tuples for matching roles."""
        user_member = User.objects.create_user(username="bf_role_mem", password="pass")
        user_manager = User.objects.create_user(username="bf_role_mgr", password="pass")
        group = Group.objects.create(name="BFRoleGroup", slug="bfrolegroup")

        GroupMembership.objects.create(
            group=group, user=user_member, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_manager, role=GroupMembership.ROLE_MANAGER,
        )

        configs = build_type_configs_from_registry()
        tuples = list(generate_through_tuples("group", configs["group"]))

        member_tuples = [t for t in tuples if t.key.relation == "member"]
        manager_tuples = [t for t in tuples if t.key.relation == "manager"]

        # Member role should only have user_member
        member_subjects = {t.key.subject for t in member_tuples}
        assert f"user:{user_member.pk}" in member_subjects
        assert f"user:{user_manager.pk}" not in member_subjects

        # Manager role should only have user_manager
        manager_subjects = {t.key.subject for t in manager_tuples}
        assert f"user:{user_manager.pk}" in manager_subjects
        assert f"user:{user_member.pk}" not in manager_subjects

    def test_backfill_with_unknown_role_skipped(self):
        """Backfill should skip memberships with unknown role values."""
        user = User.objects.create_user(username="bf_unknown", password="pass")
        group = Group.objects.create(name="BFUnknownGroup", slug="bfunknowngroup")

        # Create a membership with unknown role by bypassing validation
        membership = GroupMembership(
            group=group, user=user, role="unknown_role"
        )
        membership._meta.get_field("role").null = True
        membership.save()

        configs = build_type_configs_from_registry()
        tuples = list(generate_through_tuples("group", configs["group"]))

        # Should not generate any tuple for the unknown role
        group_tuples = [
            t for t in tuples
            if t.key.object == f"group:{group.pk}"
        ]
        assert len(group_tuples) == 0

    def test_backfill_multiple_roles_same_group(self):
        """Backfill should generate correct tuples for mixed roles in same group."""
        user_a = User.objects.create_user(username="bf_mix_a", password="pass")
        user_b = User.objects.create_user(username="bf_mix_b", password="pass")
        user_c = User.objects.create_user(username="bf_mix_c", password="pass")
        group = Group.objects.create(name="BFMixGroup", slug="bfmixgroup")

        GroupMembership.objects.create(
            group=group, user=user_a, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_b, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_c, role=GroupMembership.ROLE_MANAGER,
        )

        configs = build_type_configs_from_registry()
        tuples = list(generate_through_tuples("group", configs["group"]))

        tuples_set = {
            (t.key.object, t.key.relation, t.key.subject) for t in tuples
        }

        assert (f"group:{group.pk}", "member", f"user:{user_a.pk}") in tuples_set
        assert (f"group:{group.pk}", "member", f"user:{user_b.pk}") in tuples_set
        assert (f"group:{group.pk}", "manager", f"user:{user_c.pk}") in tuples_set


@pytest.mark.django_db(transaction=True)
class TestThroughTableNullFKs:
    """Test that NOT NULL FK constraints are enforced on through tables.

    GroupMembership has non-nullable FKs (group, user). Attempting to save with
    NULL values must raise IntegrityError. This is correct behavior — the DB
    constraints prevent invalid tuples from being created.
    """

    def test_create_with_null_group_fk_raises(self, rebac_setup):
        """Creating membership with NULL group FK raises IntegrityError."""
        user = User.objects.create_user(username="null_grp", password="pass")

        membership = GroupMembership(
            group=None, user=user, role=GroupMembership.ROLE_MEMBER
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                membership.save()

    def test_create_with_null_user_fk_raises(self, rebac_setup):
        """Creating membership with NULL user FK raises IntegrityError."""
        group = Group.objects.create(name="NullUserGroup", slug="nullusergroup")

        membership = GroupMembership(
            group=group, user=None, role=GroupMembership.ROLE_MEMBER
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                membership.save()

    def test_update_to_null_group_fk_raises(self, rebac_setup):
        """Setting group FK to NULL raises IntegrityError."""
        user = User.objects.create_user(username="upd_null_grp", password="pass")
        group = Group.objects.create(name="UpdNullGrpGroup", slug="updnullgrpgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )

        membership.group = None
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                membership.save()

    def test_update_to_null_user_fk_raises(self, rebac_setup):
        """Setting user FK to NULL raises IntegrityError."""
        user = User.objects.create_user(username="upd_null_user", password="pass")
        group = Group.objects.create(name="UpdNullUserGroup", slug="updnullusergroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )

        membership.user = None
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                membership.save()


@pytest.mark.django_db(transaction=True)
class TestThroughTableRoleTransitions:
    """Test various role transition scenarios."""

    def test_member_to_manager_transition(self, rebac_setup):
        """Transitioning from member to manager role."""
        user = User.objects.create_user(username="mem_to_mgr", password="pass")
        group = Group.objects.create(name="MemToMgrGroup", slug="memtomgrgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        membership.role = GroupMembership.ROLE_MANAGER
        membership.save()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "member", f"user:{user.pk}") in delete_tuples

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "manager", f"user:{user.pk}") in write_tuples

    def test_manager_to_member_transition(self, rebac_setup):
        """Transitioning from manager to member role."""
        user = User.objects.create_user(username="mgr_to_mem", password="pass")
        group = Group.objects.create(name="MgrToMemGroup", slug="mgrtomemgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MANAGER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        membership.role = GroupMembership.ROLE_MEMBER
        membership.save()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "manager", f"user:{user.pk}") in delete_tuples

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "member", f"user:{user.pk}") in write_tuples

    def test_multiple_transitions_same_user(self, rebac_setup):
        """Same user transitioning through multiple roles."""
        user = User.objects.create_user(username="multi_trans", password="pass")
        group = Group.objects.create(name="MultiTransGroup", slug="multitransgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )

        # First transition: member -> manager
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()
        membership.role = GroupMembership.ROLE_MANAGER
        membership.save()

        assert any(
            d.relation == "member"
            for d in rebac_setup.deletes
        )
        assert any(
            w.key.relation == "manager"
            for w in rebac_setup.writes
        )

        # Second transition: manager -> member
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()
        membership.role = GroupMembership.ROLE_MEMBER
        membership.save()

        assert any(
            d.relation == "manager"
            for d in rebac_setup.deletes
        )
        assert any(
            w.key.relation == "member"
            for w in rebac_setup.writes
        )


@pytest.mark.django_db(transaction=True)
class TestThroughTableIdempotency:
    """Test idempotent operations on through tables."""

    def test_save_without_changes_is_noop(self, rebac_setup):
        """Saving membership without changes should not sync to SpiceDB."""
        user = User.objects.create_user(username="idempotent", password="pass")
        group = Group.objects.create(name="IdempotentGroup", slug="idempotentgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Save without changes
        membership.save()

        assert len(rebac_setup.writes) == 0
        assert len(rebac_setup.deletes) == 0

    def test_multiple_same_saves_is_noop(self, rebac_setup):
        """Multiple identical saves should not produce duplicate syncs."""
        user = User.objects.create_user(username="dup_save", password="pass")
        group = Group.objects.create(name="DupSaveGroup", slug="dupsavegroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Save multiple times without changes
        membership.save()
        membership.save()
        membership.save()

        assert len(rebac_setup.writes) == 0
        assert len(rebac_setup.deletes) == 0

    def test_idempotent_role_change_back_and_forth(self, rebac_setup):
        """Changing role back to original should sync correctly."""
        user = User.objects.create_user(username="back_forth", password="pass")
        group = Group.objects.create(name="BackForthGroup", slug="backforthgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change role
        membership.role = GroupMembership.ROLE_MANAGER
        membership.save()
        writes_1 = len(rebac_setup.writes)
        deletes_1 = len(rebac_setup.deletes)

        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        # Change back to original
        membership.role = GroupMembership.ROLE_MEMBER
        membership.save()
        writes_2 = len(rebac_setup.writes)
        deletes_2 = len(rebac_setup.deletes)

        # Both transitions should have had the same work
        assert writes_1 > 0 and deletes_1 > 0
        assert writes_2 > 0 and deletes_2 > 0
