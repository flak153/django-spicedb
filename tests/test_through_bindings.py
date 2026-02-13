"""Tests for declarative through-table binding support."""

import pytest
from django.contrib.auth import get_user_model

import django_spicedb.conf as conf
from django_spicedb.core import build_type_configs_from_registry
from django_spicedb.sync import registry
from django_spicedb.sync.backfill import generate_through_tuples
from django_spicedb.types.graph import TypeGraph, TypeGraphError

from example_project.documents.models import Group, GroupMembership, Verification


User = get_user_model()


@pytest.fixture
def rebac_setup(recording_adapter):
    """Setup fixture for through-binding tests."""
    conf.reset_type_graph_cache()
    registry.refresh()
    yield recording_adapter
    conf.reset_type_graph_cache()
    registry.refresh()


class TestThroughBindingRegistration:
    """Test that through bindings appear correctly in type configs."""

    def test_through_bindings_appear_in_group_config(self):
        """Group should have through bindings for member and manager."""
        configs = build_type_configs_from_registry()
        group_cfg = configs.get("group", {})
        bindings = group_cfg.get("bindings", {})

        assert "member" in bindings
        assert bindings["member"]["kind"] == "through"
        assert bindings["member"]["model"] == "example_project.documents.models.GroupMembership"
        assert bindings["member"]["object_fk"] == "group"
        assert bindings["member"]["subject_fk"] == "user"
        assert bindings["member"]["role_field"] == "role"
        assert bindings["member"]["role_value"] == "member"

    def test_through_bindings_manager_role(self):
        """Manager binding should have correct role_value."""
        configs = build_type_configs_from_registry()
        group_cfg = configs.get("group", {})
        bindings = group_cfg.get("bindings", {})

        assert "manager" in bindings
        assert bindings["manager"]["kind"] == "through"
        assert bindings["manager"]["role_value"] == "manager"

    def test_through_bindings_pass_typegraph_validation(self):
        """TypeGraph should accept through bindings without field key."""
        configs = build_type_configs_from_registry()
        # This should not raise
        graph = TypeGraph(configs)
        group_type = graph.types["group"]
        assert "member" in group_type.bindings
        assert "manager" in group_type.bindings
        assert group_type.bindings["member"]["kind"] == "through"


class TestThroughBindingValidation:
    """Test that TypeGraph validates through bindings correctly."""

    def test_through_binding_missing_model_raises(self):
        """Through binding without model should raise TypeGraphError."""
        configs = {
            "user": {"model": "django.contrib.auth.models.User"},
            "group": {
                "model": "example_project.documents.models.Group",
                "relations": {"member": "user"},
                "bindings": {
                    "member": {
                        "kind": "through",
                        "object_fk": "group",
                        "subject_fk": "user",
                    },
                },
            },
        }
        with pytest.raises(TypeGraphError, match="model"):
            TypeGraph(configs)

    def test_through_binding_missing_object_fk_raises(self):
        """Through binding without object_fk should raise TypeGraphError."""
        configs = {
            "user": {"model": "django.contrib.auth.models.User"},
            "group": {
                "model": "example_project.documents.models.Group",
                "relations": {"member": "user"},
                "bindings": {
                    "member": {
                        "kind": "through",
                        "model": "example_project.documents.models.GroupMembership",
                        "subject_fk": "user",
                    },
                },
            },
        }
        with pytest.raises(TypeGraphError, match="object_fk"):
            TypeGraph(configs)

    def test_through_binding_missing_subject_fk_raises(self):
        """Through binding without subject_fk should raise TypeGraphError."""
        configs = {
            "user": {"model": "django.contrib.auth.models.User"},
            "group": {
                "model": "example_project.documents.models.Group",
                "relations": {"member": "user"},
                "bindings": {
                    "member": {
                        "kind": "through",
                        "model": "example_project.documents.models.GroupMembership",
                        "object_fk": "group",
                    },
                },
            },
        }
        with pytest.raises(TypeGraphError, match="subject_fk"):
            TypeGraph(configs)

    def test_through_binding_valid_passes(self):
        """Complete through binding should pass validation."""
        configs = {
            "user": {"model": "django.contrib.auth.models.User"},
            "group": {
                "model": "example_project.documents.models.Group",
                "relations": {"member": "user"},
                "bindings": {
                    "member": {
                        "kind": "through",
                        "model": "example_project.documents.models.GroupMembership",
                        "object_fk": "group",
                        "subject_fk": "user",
                        "role_field": "role",
                        "role_value": "member",
                    },
                },
            },
        }
        graph = TypeGraph(configs)
        assert "member" in graph.types["group"].bindings


@pytest.mark.django_db(transaction=True)
class TestThroughSignalSync:
    """Test that through-table signal handlers work correctly."""

    def test_create_membership_writes_tuple(self, rebac_setup):
        """Creating a membership should write the correct tuple."""
        user = User.objects.create_user(username="throughuser", password="pass")
        group = Group.objects.create(name="ThroughGroup", slug="throughgroup")

        GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "member", f"user:{user.pk}") in write_tuples

    def test_create_manager_writes_manager_tuple(self, rebac_setup):
        """Creating a manager membership should write manager tuple."""
        user = User.objects.create_user(username="throughmgr", password="pass")
        group = Group.objects.create(name="ThroughMgrGroup", slug="throughmgrgroup")

        GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MANAGER,
        )

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group.pk}", "manager", f"user:{user.pk}") in write_tuples

    def test_role_change_deletes_old_writes_new(self, rebac_setup):
        """Changing role should delete old tuple and write new one."""
        user = User.objects.create_user(username="rolechange", password="pass")
        group = Group.objects.create(name="RoleGroup", slug="rolegroup")

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

    def test_delete_membership_removes_tuple(self, rebac_setup):
        """Deleting membership should delete the tuple."""
        user = User.objects.create_user(username="delthrough", password="pass")
        group = Group.objects.create(name="DelGroup", slug="delgroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        membership.delete()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group.pk}", "member", f"user:{user.pk}") in delete_tuples

    def test_no_change_save_skips(self, rebac_setup):
        """Saving without changes should not write or delete."""
        user = User.objects.create_user(username="nochange", password="pass")
        group = Group.objects.create(name="NoChangeGroup", slug="nochangegroup")

        membership = GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        membership.save()

        assert len(rebac_setup.writes) == 0
        assert len(rebac_setup.deletes) == 0

    def test_group_fk_change_deletes_old_writes_new(self, rebac_setup):
        """Changing the group FK should produce correct delete + write."""
        user = User.objects.create_user(username="grpchange", password="pass")
        group_a = Group.objects.create(name="GroupA", slug="grpchangea")
        group_b = Group.objects.create(name="GroupB", slug="grpchangeb")

        membership = GroupMembership.objects.create(
            group=group_a, user=user, role=GroupMembership.ROLE_MEMBER,
        )
        rebac_setup.writes.clear()
        rebac_setup.deletes.clear()

        membership.group = group_b
        membership.save()

        delete_tuples = {
            (d.object, d.relation, d.subject) for d in rebac_setup.deletes
        }
        assert (f"group:{group_a.pk}", "member", f"user:{user.pk}") in delete_tuples

        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in rebac_setup.writes
        }
        assert (f"group:{group_b.pk}", "member", f"user:{user.pk}") in write_tuples


@pytest.mark.django_db
class TestThroughBackfill:
    """Test backfill support for through bindings."""

    def test_generate_through_tuples_member(self):
        """generate_through_tuples should produce member tuples."""
        user = User.objects.create_user(username="bfmember", password="pass")
        group = Group.objects.create(name="BFGroup", slug="bfgroup")
        GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MEMBER,
        )

        configs = build_type_configs_from_registry()
        tuples = list(generate_through_tuples("group", configs["group"]))

        member_tuples = [
            t for t in tuples
            if t.key.relation == "member"
            and t.key.object == f"group:{group.pk}"
            and t.key.subject == f"user:{user.pk}"
        ]
        assert len(member_tuples) == 1

    def test_generate_through_tuples_manager(self):
        """generate_through_tuples should produce manager tuples."""
        user = User.objects.create_user(username="bfmanager", password="pass")
        group = Group.objects.create(name="BFMgrGroup", slug="bfmgrgroup")
        GroupMembership.objects.create(
            group=group, user=user, role=GroupMembership.ROLE_MANAGER,
        )

        configs = build_type_configs_from_registry()
        tuples = list(generate_through_tuples("group", configs["group"]))

        manager_tuples = [
            t for t in tuples
            if t.key.relation == "manager"
            and t.key.object == f"group:{group.pk}"
            and t.key.subject == f"user:{user.pk}"
        ]
        assert len(manager_tuples) == 1

    def test_generate_through_tuples_filters_by_role(self):
        """Each role binding should only yield rows with matching role."""
        user_m = User.objects.create_user(username="bffilterm", password="pass")
        user_g = User.objects.create_user(username="bffilterg", password="pass")
        group = Group.objects.create(name="BFFilterGroup", slug="bffiltergroup")
        GroupMembership.objects.create(
            group=group, user=user_m, role=GroupMembership.ROLE_MEMBER,
        )
        GroupMembership.objects.create(
            group=group, user=user_g, role=GroupMembership.ROLE_MANAGER,
        )

        configs = build_type_configs_from_registry()
        tuples = list(generate_through_tuples("group", configs["group"]))

        member_tuples = [t for t in tuples if t.key.relation == "member"]
        manager_tuples = [t for t in tuples if t.key.relation == "manager"]

        # member binding only picks up user_m
        assert len(member_tuples) == 1
        assert member_tuples[0].key.subject == f"user:{user_m.pk}"

        # manager binding only picks up user_g
        assert len(manager_tuples) == 1
        assert manager_tuples[0].key.subject == f"user:{user_g.pk}"
