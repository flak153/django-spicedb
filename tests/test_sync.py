from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

import django_rebac.conf as conf
from django_rebac.sync import registry
from django_rebac.sync.registry import (
    _get_fk_value,
    _gather_tuple_writes,
    _parse_subject,
    _format_subject,
)
from django_rebac.types.graph import TypeConfig

from example_project.documents.models import Document, Workspace, Folder, HierarchyResource


@pytest.fixture
def sync_rebac_setup(recording_adapter):
    """Setup fixture that uses model-based RebacMeta configuration."""
    conf.reset_type_graph_cache()
    registry.refresh()
    yield
    conf.reset_type_graph_cache()
    registry.refresh()


@pytest.mark.django_db(transaction=True)
def test_fk_and_m2m_bindings(sync_rebac_setup, recording_adapter):
    """Test that FK and M2M field changes write/delete tuples."""

    User = get_user_model()
    owner = User.objects.create_user(username="owner", password="pass")
    member = User.objects.create_user(username="member", password="pass")

    # Test M2M binding: Workspace.members -> user
    workspace = Workspace.objects.create(name="Acme")
    workspace.members.add(member)

    # Test FK binding: Folder.owner -> user, Folder.parent -> folder
    root_folder = Folder.objects.create(name="Root", owner=owner)
    child_folder = Folder.objects.create(name="Child", owner=owner, parent=root_folder)

    # Test FK binding: Document.owner -> user, Document.parent -> folder
    document = Document.objects.create(
        title="Spec",
        owner=owner,
        workspace=workspace,
        folder=child_folder,
    )

    write_tuples = {
        (w.key.object, w.key.relation, w.key.subject)
        for w in recording_adapter.writes
    }

    # Workspace member binding
    assert (
        f"workspace:{workspace.pk}",
        "member",
        f"user:{member.pk}",
    ) in write_tuples

    # Document owner binding
    assert (
        f"document:{document.pk}",
        "owner",
        f"user:{owner.pk}",
    ) in write_tuples

    # Document parent (folder) binding
    assert (
        f"document:{document.pk}",
        "parent",
        f"folder:{child_folder.pk}",
    ) in write_tuples

    # Folder owner binding
    assert (
        f"folder:{root_folder.pk}",
        "owner",
        f"user:{owner.pk}",
    ) in write_tuples

    # Folder parent binding
    assert (
        f"folder:{child_folder.pk}",
        "parent",
        f"folder:{root_folder.pk}",
    ) in write_tuples

    # Test delete: deleting folder should delete parent tuple
    child_folder_pk = child_folder.pk
    root_folder_pk = root_folder.pk
    child_folder.delete()
    delete_tuples = {
        (d.object, d.relation, d.subject)
        for d in recording_adapter.deletes
    }
    assert (
        f"folder:{child_folder_pk}",
        "parent",
        f"folder:{root_folder_pk}",
    ) in delete_tuples

    # Test M2M delete: removing member should delete tuple
    workspace.members.remove(member)
    delete_tuples = {
        (d.object, d.relation, d.subject)
        for d in recording_adapter.deletes
    }

    assert (
        f"workspace:{workspace.pk}",
        "member",
        f"user:{member.pk}",
    ) in delete_tuples


@pytest.mark.django_db(transaction=True)
def test_hierarchy_resource_bindings(sync_rebac_setup, recording_adapter):
    """Test HierarchyResource FK and M2M bindings."""

    User = get_user_model()
    owner = User.objects.create_user(username="manager", password="pass")

    root = HierarchyResource.objects.create(name="Root")
    child = HierarchyResource.objects.create(name="Child", parent=root)

    # Add manager via M2M
    root.managers.add(owner)

    write_tuples = {
        (w.key.object, w.key.relation, w.key.subject)
        for w in recording_adapter.writes
    }

    # HierarchyResource parent binding
    assert (
        f"hierarchy_resource:{child.pk}",
        "parent",
        f"hierarchy_resource:{root.pk}",
    ) in write_tuples

    # HierarchyResource manager binding (M2M)
    assert (
        f"hierarchy_resource:{root.pk}",
        "manager",
        f"user:{owner.pk}",
    ) in write_tuples


@pytest.mark.django_db
class TestGetFkValue:
    """Test the _get_fk_value helper function used for subject_field/object_field."""

    def test_get_fk_value_with_pk(self):
        """When attribute is 'pk', should return the FK ID without hitting DB."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Test", owner=owner)

        # Test getting FK ID using 'pk' attribute
        result = _get_fk_value(folder, "owner", "pk")
        assert result == owner.pk

    def test_get_fk_value_with_pk_uses_cache(self):
        """When attribute is 'pk', should use _id cache if available."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Test", owner=owner)

        # The folder.__dict__ should have owner_id cached
        assert "owner_id" in folder.__dict__

        # _get_fk_value should use the cache
        result = _get_fk_value(folder, "owner", "pk")
        assert result == owner.pk

    def test_get_fk_value_with_custom_attribute(self):
        """When attribute is not 'pk', should get that attribute from related object."""
        User = get_user_model()
        owner = User.objects.create_user(username="testowner", password="pass")
        folder = Folder.objects.create(name="Test", owner=owner)

        # Test getting username from the related User
        result = _get_fk_value(folder, "owner", "username")
        assert result == "testowner"

    def test_get_fk_value_with_null_fk(self):
        """When FK is null, should return None."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Test", owner=owner, parent=None)

        # parent is null
        result = _get_fk_value(folder, "parent", "pk")
        assert result is None

    def test_get_fk_value_with_null_fk_custom_attribute(self):
        """When FK is null and using custom attribute, should return None."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Test", owner=owner, parent=None)

        # parent is null, trying to get 'name' attribute
        result = _get_fk_value(folder, "parent", "name")
        assert result is None


@pytest.mark.django_db(transaction=True)
class TestSubjectFieldTracking:
    """Test FK change tracking with subject_field (non-pk attributes)."""

    def test_subject_field_in_binding_config(self, sync_rebac_setup, recording_adapter):
        """Verify that subject_field is respected in tuple generation.

        This test verifies the _get_fk_value helper is called correctly
        when generating tuples. The actual tuple format depends on config.
        """
        User = get_user_model()
        owner = User.objects.create_user(username="owner1", password="pass")

        # Create a folder with owner
        folder = Folder.objects.create(name="Test", owner=owner)

        # Verify the tuple was written using the owner's pk (default behavior)
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in recording_adapter.writes
        }

        assert (
            f"folder:{folder.pk}",
            "owner",
            f"user:{owner.pk}",
        ) in write_tuples

    def test_fk_change_deletes_old_tuple_correctly(self, sync_rebac_setup, recording_adapter):
        """When FK changes, the old tuple should be deleted with old values."""
        User = get_user_model()
        owner1 = User.objects.create_user(username="owner1", password="pass")
        owner2 = User.objects.create_user(username="owner2", password="pass")

        # Create folder with owner1
        folder = Folder.objects.create(name="Test", owner=owner1)

        # Clear previous writes
        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        # Change owner to owner2
        folder.owner = owner2
        folder.save()

        # Check old tuple was deleted
        delete_tuples = {
            (d.object, d.relation, d.subject)
            for d in recording_adapter.deletes
        }
        assert (
            f"folder:{folder.pk}",
            "owner",
            f"user:{owner1.pk}",
        ) in delete_tuples

        # Check new tuple was written
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in recording_adapter.writes
        }
        assert (
            f"folder:{folder.pk}",
            "owner",
            f"user:{owner2.pk}",
        ) in write_tuples

    def test_null_parent_to_value_does_not_delete_type_none(self, sync_rebac_setup, recording_adapter):
        """Changing parent from null to value should NOT try to delete type:None."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")

        # Create root folder (no parent)
        root = Folder.objects.create(name="Root", owner=owner, parent=None)

        # Create child folder with no parent initially
        child = Folder.objects.create(name="Child", owner=owner, parent=None)

        # Clear previous writes/deletes
        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        # Now set parent (null -> value)
        child.parent = root
        child.save()

        # Should NOT have deleted folder:None (that tuple never existed)
        for delete in recording_adapter.deletes:
            assert "None" not in delete.object, f"Should not delete type:None tuple: {delete}"

        # Should have written the new parent tuple
        write_tuples = {
            (w.key.object, w.key.relation, w.key.subject)
            for w in recording_adapter.writes
        }
        assert (
            f"folder:{child.pk}",
            "parent",
            f"folder:{root.pk}",
        ) in write_tuples


@pytest.mark.django_db
class TestGatherTupleWritesWithSubjectField:
    """Test _gather_tuple_writes with custom subject_field configs."""

    def test_subject_field_uses_custom_attribute(self):
        """subject_field should use the specified attribute from related object."""
        User = get_user_model()
        owner = User.objects.create_user(username="alice", password="pass")
        folder = Folder.objects.create(name="Test", owner=owner)

        # Create a config that uses username as subject_field
        cfg = TypeConfig(
            name="folder",
            model="example_project.documents.models.Folder",
            relations={"owner": "user"},
            permissions={},
            bindings={
                "owner": {
                    "field": "owner",
                    "kind": "fk",
                    "subject_field": "username",  # Use username instead of pk
                }
            },
        )

        writes = list(_gather_tuple_writes("folder", cfg, folder))

        assert len(writes) == 1
        assert writes[0].key.object == f"folder:{folder.pk}"
        assert writes[0].key.relation == "owner"
        assert writes[0].key.subject == "user:alice"  # Uses username, not pk

    def test_object_field_uses_fk_pk(self):
        """object_field should use the specified FK's pk as the object ID."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        root = Folder.objects.create(name="Root", owner=owner)
        child = Folder.objects.create(name="Child", owner=owner, parent=root)

        # Create a config that uses parent's pk as object_field
        # This simulates a "join table" pattern where tuple is written on parent
        cfg = TypeConfig(
            name="folder",
            model="example_project.documents.models.Folder",
            relations={"child_owner": "user"},
            permissions={},
            bindings={
                "child_owner": {
                    "field": "owner",
                    "kind": "fk",
                    "object_field": "parent",  # Use parent.pk as object instead of self.pk
                }
            },
        )

        writes = list(_gather_tuple_writes("folder", cfg, child))

        assert len(writes) == 1
        # Object should be parent's pk, not child's pk
        assert writes[0].key.object == f"folder:{root.pk}"
        assert writes[0].key.relation == "child_owner"
        assert writes[0].key.subject == f"user:{owner.pk}"

    def test_object_field_null_skips_write(self):
        """When object_field FK is null, no tuple should be written."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        # Folder with no parent
        folder = Folder.objects.create(name="Root", owner=owner, parent=None)

        cfg = TypeConfig(
            name="folder",
            model="example_project.documents.models.Folder",
            relations={"child_owner": "user"},
            permissions={},
            bindings={
                "child_owner": {
                    "field": "owner",
                    "kind": "fk",
                    "object_field": "parent",  # parent is null
                }
            },
        )

        writes = list(_gather_tuple_writes("folder", cfg, folder))

        # No tuple should be written since object_field (parent) is null
        assert len(writes) == 0

    def test_subject_field_null_skips_write(self):
        """When subject FK is null, no tuple should be written."""
        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Root", owner=owner, parent=None)

        cfg = TypeConfig(
            name="folder",
            model="example_project.documents.models.Folder",
            relations={"parent": "folder"},
            permissions={},
            bindings={
                "parent": {
                    "field": "parent",  # parent is null
                    "kind": "fk",
                }
            },
        )

        writes = list(_gather_tuple_writes("folder", cfg, folder))

        # No tuple should be written since subject FK (parent) is null
        assert len(writes) == 0


@pytest.mark.django_db(transaction=True)
class TestSubjectFieldObjectFieldRealSignals:
    """
    Black-box integration tests using real Django signals with custom configs.

    These tests wire up _register_model with custom subject_field/object_field
    configs and verify the actual signal handlers produce correct tuples.
    """

    def test_subject_field_real_signals_fk_change(self, recording_adapter):
        """
        Test REAL signal flow with subject_field: username.

        Wires up a custom config, triggers actual saves, verifies adapter
        receives correct delete (old username) and write (new username).
        """
        from django.db.models.signals import pre_save, post_save, post_delete
        from django_rebac.sync.registry import _register_model, _disconnect_all, _REGISTERED

        User = get_user_model()
        alice = User.objects.create_user(username="alice", password="pass")
        bob = User.objects.create_user(username="bob", password="pass")

        # Forcibly disconnect Document signals by dispatch_uid
        pre_save.disconnect(sender=Document, dispatch_uid="rebac_pre_save_document")
        post_save.disconnect(sender=Document, dispatch_uid="rebac_post_save_document")
        post_delete.disconnect(sender=Document, dispatch_uid="rebac_post_delete_document")
        # Clear registry entry if present
        _REGISTERED.pop(Document, None)

        # Config with subject_field: username
        cfg = TypeConfig(
            name="document",
            model="example_project.documents.models.Document",
            relations={"owner": "user"},
            permissions={"view": "owner"},
            bindings={
                "owner": {
                    "field": "owner",
                    "kind": "fk",
                    "subject_field": "username",  # Use username, not pk
                }
            },
        )

        # Register with custom config - this wires up REAL signal handlers
        _register_model("document", Document, cfg)

        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        try:
            # Create document - should write tuple with alice's username
            doc = Document.objects.create(title="Test", owner=alice)

            # Verify write used username
            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }
            assert (f"document:{doc.pk}", "owner", "user:alice") in write_tuples

            # Clear for next operation
            recording_adapter.writes.clear()
            recording_adapter.deletes.clear()

            # Change owner - should delete old (alice) and write new (bob)
            doc.owner = bob
            doc.save()

            # Verify delete used alice's USERNAME
            delete_tuples = {
                (d.object, d.relation, d.subject)
                for d in recording_adapter.deletes
            }
            assert (f"document:{doc.pk}", "owner", "user:alice") in delete_tuples

            # Verify write used bob's USERNAME
            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }
            assert (f"document:{doc.pk}", "owner", "user:bob") in write_tuples

        finally:
            # Restore normal registry
            _disconnect_all()
            conf.reset_type_graph_cache()
            registry.refresh()

    def test_object_field_real_signals_fk_change(self, recording_adapter):
        """
        Test REAL signal flow with object_field: parent.

        Wires up a custom config where tuples are written on parent's pk,
        triggers actual saves, verifies delete uses old parent.pk.
        """
        from django.db.models.signals import pre_save, post_save, post_delete
        from django_rebac.sync.registry import _register_model, _disconnect_all, _REGISTERED

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")

        # Forcibly disconnect Folder signals by dispatch_uid
        pre_save.disconnect(sender=Folder, dispatch_uid="rebac_pre_save_folder")
        post_save.disconnect(sender=Folder, dispatch_uid="rebac_post_save_folder")
        post_delete.disconnect(sender=Folder, dispatch_uid="rebac_post_delete_folder")
        _REGISTERED.pop(Folder, None)

        # Create folders without signals
        root1 = Folder.objects.create(name="Root1", owner=owner)
        root2 = Folder.objects.create(name="Root2", owner=owner)

        # Config with object_field: parent
        cfg = TypeConfig(
            name="folder",
            model="example_project.documents.models.Folder",
            relations={"child_owner": "user"},
            permissions={},
            bindings={
                "child_owner": {
                    "field": "owner",
                    "kind": "fk",
                    "object_field": "parent",  # Use parent.pk as object
                }
            },
        )

        # Register with custom config
        _register_model("folder", Folder, cfg)

        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        try:
            # Create child with parent=root1
            child = Folder.objects.create(name="Child", owner=owner, parent=root1)

            # Verify write used root1's pk as object
            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }
            assert (f"folder:{root1.pk}", "child_owner", f"user:{owner.pk}") in write_tuples

            # Clear for next operation
            recording_adapter.writes.clear()
            recording_adapter.deletes.clear()

            # Change parent to root2
            child.parent = root2
            child.save()

            # Verify delete used root1's pk (old parent)
            delete_tuples = {
                (d.object, d.relation, d.subject)
                for d in recording_adapter.deletes
            }
            assert (f"folder:{root1.pk}", "child_owner", f"user:{owner.pk}") in delete_tuples

            # Verify write used root2's pk (new parent)
            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }
            assert (f"folder:{root2.pk}", "child_owner", f"user:{owner.pk}") in write_tuples

        finally:
            _disconnect_all()
            conf.reset_type_graph_cache()
            registry.refresh()

    def test_null_object_field_no_delete_real_signals(self, recording_adapter):
        """
        Test REAL signal flow: null→value transition doesn't delete type:None.
        """
        from django.db.models.signals import pre_save, post_save, post_delete
        from django_rebac.sync.registry import _register_model, _disconnect_all, _REGISTERED

        User = get_user_model()
        owner = User.objects.create_user(username="owner", password="pass")

        # Forcibly disconnect Folder signals by dispatch_uid
        pre_save.disconnect(sender=Folder, dispatch_uid="rebac_pre_save_folder")
        post_save.disconnect(sender=Folder, dispatch_uid="rebac_post_save_folder")
        post_delete.disconnect(sender=Folder, dispatch_uid="rebac_post_delete_folder")
        _REGISTERED.pop(Folder, None)

        # Create root folder without signals
        root = Folder.objects.create(name="Root", owner=owner)

        # Config with object_field: parent
        cfg = TypeConfig(
            name="folder",
            model="example_project.documents.models.Folder",
            relations={"child_owner": "user"},
            permissions={},
            bindings={
                "child_owner": {
                    "field": "owner",
                    "kind": "fk",
                    "object_field": "parent",
                }
            },
        )

        _register_model("folder", Folder, cfg)

        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        try:
            # Create child with NO parent - no tuple should be written
            child = Folder.objects.create(name="Child", owner=owner, parent=None)

            # No write (object_field is null)
            child_owner_writes = [
                w for w in recording_adapter.writes
                if w.key.relation == "child_owner"
            ]
            assert len(child_owner_writes) == 0

            recording_adapter.writes.clear()
            recording_adapter.deletes.clear()

            # Set parent (null → value)
            child.parent = root
            child.save()

            # Should NOT delete type:None
            for d in recording_adapter.deletes:
                assert "None" not in d.object, f"Should not delete type:None: {d}"

            # Should write new tuple
            write_tuples = {
                (w.key.object, w.key.relation, w.key.subject)
                for w in recording_adapter.writes
            }
            assert (f"folder:{root.pk}", "child_owner", f"user:{owner.pk}") in write_tuples

        finally:
            _disconnect_all()
            conf.reset_type_graph_cache()
            registry.refresh()
