"""Tests for RebacModel public API methods: grant(), revoke(), and has_perm()."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from django_spicedb.adapters import reset_adapter, set_adapter
from django_spicedb.adapters.base import TupleKey, TupleWrite
from example_project.documents.models import Document, Folder, Workspace


User = get_user_model()


@pytest.fixture
def recording_adapter_instance(recording_adapter):
    """Provide recording adapter via conftest fixture."""
    return recording_adapter


@pytest.mark.django_db
class TestGrantWithDjangoModelInstance:
    """Test grant() method with Django model instance as subject."""

    def test_grant_with_model_instance_writes_correct_tuple(
        self, recording_adapter_instance
    ):
        """Verify grant() writes a tuple with correct object, relation, and subject."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # Clear any auto-generated tuples from document creation
        recording_adapter_instance.writes.clear()

        # Call grant
        document.grant(member, "editor")

        # Verify tuple was written
        assert len(recording_adapter_instance.writes) == 1
        write = recording_adapter_instance.writes[0]
        assert write.key.object == f"document:{document.pk}"
        assert write.key.relation == "editor"
        assert write.key.subject == f"user:{member.pk}"

    def test_grant_with_user_model_builds_correct_subject_reference(
        self, recording_adapter_instance
    ):
        """Verify grant() correctly identifies the subject type from User model."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()
        document.grant(member, "viewer")

        write = recording_adapter_instance.writes[0]
        # Subject should be formatted as "user:id"
        assert write.key.subject.startswith("user:")
        assert str(member.pk) in write.key.subject

    def test_grant_with_folder_model_builds_correct_subject_reference(
        self, recording_adapter_instance
    ):
        """Verify grant() correctly identifies folder type when subject is Folder."""
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Parent", owner=owner)
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()
        document.grant(folder, "parent")

        write = recording_adapter_instance.writes[0]
        # Subject should be formatted as "folder:id"
        assert write.key.subject == f"folder:{folder.pk}"


@pytest.mark.django_db
class TestGrantWithStringSubject:
    """Test grant() method with string subject reference."""

    def test_grant_with_string_subject_writes_tuple_unchanged(
        self, recording_adapter_instance
    ):
        """Verify grant() accepts and writes string subjects as-is."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()

        # Call grant with string subject
        document.grant("user:123", "editor")

        # Verify tuple was written with string subject
        assert len(recording_adapter_instance.writes) == 1
        write = recording_adapter_instance.writes[0]
        assert write.key.object == f"document:{document.pk}"
        assert write.key.relation == "editor"
        assert write.key.subject == "user:123"

    def test_grant_with_arbitrary_type_string_subject(self, recording_adapter_instance):
        """Verify grant() works with any type:id string format."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()

        # String subject with different type
        document.grant("group:456", "collaborator")

        write = recording_adapter_instance.writes[0]
        assert write.key.subject == "group:456"


@pytest.mark.django_db
class TestGrantOnUnsavedModel:
    """Test grant() with unsaved model instance."""

    def test_grant_on_unsaved_model_raises_error(
        self, recording_adapter_instance
    ):
        """Verify grant() on unsaved model raises ImproperlyConfigured.

        Granting permissions on an unsaved instance would create a tuple with
        None as the pk, which is invalid. The code correctly prevents this.
        """
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")

        # Create unsaved document
        document = Document(title="Unsaved", owner=owner)

        with pytest.raises(ImproperlyConfigured, match="Cannot grant permissions on an unsaved model instance"):
            document.grant(member, "editor")


@pytest.mark.django_db
class TestRevokeWithDjangoModelInstance:
    """Test revoke() method with Django model instance as subject."""

    def test_revoke_with_model_instance_deletes_correct_tuple(
        self, recording_adapter_instance
    ):
        """Verify revoke() deletes a tuple with correct object, relation, and subject."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # Clear auto-generated tuples
        recording_adapter_instance.deletes.clear()

        # Call revoke
        document.revoke(member, "editor")

        # Verify tuple was deleted
        assert len(recording_adapter_instance.deletes) == 1
        delete = recording_adapter_instance.deletes[0]
        assert delete.object == f"document:{document.pk}"
        assert delete.relation == "editor"
        assert delete.subject == f"user:{member.pk}"

    def test_revoke_with_user_model_builds_correct_subject_reference(
        self, recording_adapter_instance
    ):
        """Verify revoke() correctly formats User model as subject."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.deletes.clear()
        document.revoke(member, "viewer")

        delete = recording_adapter_instance.deletes[0]
        # Subject should be formatted as "user:id"
        assert delete.subject.startswith("user:")
        assert str(member.pk) in delete.subject

    def test_revoke_with_folder_model_builds_correct_subject_reference(
        self, recording_adapter_instance
    ):
        """Verify revoke() correctly identifies folder type when subject is Folder."""
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Parent", owner=owner)
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.deletes.clear()
        document.revoke(folder, "parent")

        delete = recording_adapter_instance.deletes[0]
        # Subject should be formatted as "folder:id"
        assert delete.subject == f"folder:{folder.pk}"


@pytest.mark.django_db
class TestRevokeWithStringSubject:
    """Test revoke() method with string subject reference."""

    def test_revoke_with_string_subject_deletes_tuple_unchanged(
        self, recording_adapter_instance
    ):
        """Verify revoke() accepts and deletes string subjects as-is."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.deletes.clear()

        # Call revoke with string subject
        document.revoke("user:123", "editor")

        # Verify tuple was deleted with string subject
        assert len(recording_adapter_instance.deletes) == 1
        delete = recording_adapter_instance.deletes[0]
        assert delete.object == f"document:{document.pk}"
        assert delete.relation == "editor"
        assert delete.subject == "user:123"

    def test_revoke_with_arbitrary_type_string_subject(
        self, recording_adapter_instance
    ):
        """Verify revoke() works with any type:id string format."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.deletes.clear()

        # String subject with different type
        document.revoke("group:456", "collaborator")

        delete = recording_adapter_instance.deletes[0]
        assert delete.subject == "group:456"


@pytest.mark.django_db
class TestRevokeOnUnsavedModel:
    """Test revoke() with unsaved model instance."""

    def test_revoke_on_unsaved_model_raises_error(
        self, recording_adapter_instance
    ):
        """Verify revoke() on unsaved model raises ImproperlyConfigured.

        Revoking permissions on an unsaved instance would create a tuple
        deletion with None as the pk, which is invalid. The code correctly
        prevents this.
        """
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")

        # Create unsaved document
        document = Document(title="Unsaved", owner=owner)

        with pytest.raises(ImproperlyConfigured, match="Cannot revoke permissions on an unsaved model instance"):
            document.revoke(member, "editor")


@pytest.mark.django_db
class TestHasPermWithDjangoModelInstance:
    """Test has_perm() method with Django model instance as subject."""

    def test_has_perm_returns_true_when_adapter_check_returns_true(
        self, recording_adapter_instance
    ):
        """Verify has_perm() returns True when adapter.check() returns True."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # Setup adapter to return True for this check
        recording_adapter_instance.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        # Call has_perm
        result = document.has_perm(owner, "view")

        assert result is True

    def test_has_perm_returns_false_when_adapter_check_returns_false(
        self, recording_adapter_instance
    ):
        """Verify has_perm() returns False when adapter.check() returns False."""
        owner = User.objects.create_user(username="owner", password="pass")
        viewer = User.objects.create_user(username="viewer", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # Setup adapter to return False (default behavior)
        recording_adapter_instance.set_check_response(
            subject=f"user:{viewer.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=False,
        )

        result = document.has_perm(viewer, "view")

        assert result is False

    def test_has_perm_calls_adapter_check_with_correct_arguments(
        self, recording_adapter_instance
    ):
        """Verify has_perm() passes correct subject, relation, and object to adapter."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.set_check_response(
            subject=f"user:{owner.pk}",
            relation="edit",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        document.has_perm(owner, "edit")

        # Verify check was called with correct parameters
        assert len(recording_adapter_instance.check_calls) >= 1
        call = recording_adapter_instance.check_calls[0]
        assert call[0] == f"user:{owner.pk}"  # subject
        assert call[1] == "edit"  # relation
        assert call[2] == f"document:{document.pk}"  # object


@pytest.mark.django_db
class TestHasPermWithStringSubject:
    """Test has_perm() method with string subject reference."""

    def test_has_perm_works_with_string_subject(self, recording_adapter_instance):
        """Verify has_perm() accepts string subjects."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # Setup adapter to return True for string subject
        recording_adapter_instance.set_check_response(
            subject="user:123",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        result = document.has_perm("user:123", "view")

        assert result is True

    def test_has_perm_with_arbitrary_type_string_subject(
        self, recording_adapter_instance
    ):
        """Verify has_perm() works with any type:id string format."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.set_check_response(
            subject="group:456",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        result = document.has_perm("group:456", "view")

        assert result is True


@pytest.mark.django_db
class TestHasPermOnUnsavedModel:
    """Test has_perm() raises error when called on unsaved model instance."""

    def test_has_perm_on_unsaved_object_raises_error(self, recording_adapter_instance):
        """Verify has_perm() raises error when object pk is None."""
        owner = User.objects.create_user(username="owner", password="pass")

        # Create unsaved document
        document = Document(title="Unsaved", owner=owner)

        # has_perm() should raise ImproperlyConfigured because document.pk is None
        with pytest.raises(ImproperlyConfigured):
            document.has_perm(owner, "view")

    def test_has_perm_with_unsaved_subject_raises_error(
        self, recording_adapter_instance
    ):
        """Verify has_perm() raises error when subject (model instance) is unsaved."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # Create unsaved subject
        unsaved_viewer = User(username="unsaved")

        # has_perm() should raise ImproperlyConfigured because subject.pk is None
        with pytest.raises(ImproperlyConfigured):
            document.has_perm(unsaved_viewer, "view")


@pytest.mark.django_db
class TestGrantThenRevokeSameTuple:
    """Test granting then revoking the same tuple (basic idempotency check)."""

    def test_grant_then_revoke_records_both_operations(
        self, recording_adapter_instance
    ):
        """Verify grant followed by revoke records both operations."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()
        recording_adapter_instance.deletes.clear()

        # Grant
        document.grant(member, "editor")
        assert len(recording_adapter_instance.writes) == 1

        # Revoke
        document.revoke(member, "editor")
        assert len(recording_adapter_instance.deletes) == 1

        # Verify same tuple (same object, relation, subject)
        write = recording_adapter_instance.writes[0]
        delete = recording_adapter_instance.deletes[0]

        assert write.key.object == delete.object
        assert write.key.relation == delete.relation
        assert write.key.subject == delete.subject


@pytest.mark.django_db
class TestGrantSameTupleTwice:
    """Test granting the same tuple multiple times."""

    def test_grant_same_tuple_twice_records_both_writes(
        self, recording_adapter_instance
    ):
        """Verify calling grant() twice records both write operations."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()

        # Grant same tuple twice
        document.grant(member, "editor")
        document.grant(member, "editor")

        # Both writes should be recorded (no de-duplication at this level)
        assert len(recording_adapter_instance.writes) == 2

        # Both should be identical
        write1 = recording_adapter_instance.writes[0]
        write2 = recording_adapter_instance.writes[1]

        assert write1.key == write2.key


@pytest.mark.django_db
class TestHasPermWithNoneSubject:
    """Test has_perm() behavior with None subject."""

    def test_has_perm_with_none_subject_raises_error(self, recording_adapter_instance):
        """Verify has_perm() raises error when subject is None."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # has_perm() with None should raise ImproperlyConfigured
        with pytest.raises(ImproperlyConfigured):
            document.has_perm(None, "view")


@pytest.mark.django_db
class TestHasPermWithDifferentPermissions:
    """Test has_perm() with different permission names."""

    def test_has_perm_with_view_permission(self, recording_adapter_instance):
        """Verify has_perm() works with 'view' permission."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        result = document.has_perm(owner, "view")
        assert result is True

    def test_has_perm_with_edit_permission(self, recording_adapter_instance):
        """Verify has_perm() works with 'edit' permission."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.set_check_response(
            subject=f"user:{owner.pk}",
            relation="edit",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        result = document.has_perm(owner, "edit")
        assert result is True

    def test_has_perm_with_custom_permission_name(self, recording_adapter_instance):
        """Verify has_perm() works with any permission name."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.set_check_response(
            subject=f"user:{owner.pk}",
            relation="delete",
            object_ref=f"document:{document.pk}",
            result=False,
        )

        result = document.has_perm(owner, "delete")
        assert result is False


@pytest.mark.django_db
class TestGrantRevokeWithDifferentModels:
    """Test grant/revoke with models of different types."""

    def test_grant_folder_as_subject_to_document(self, recording_adapter_instance):
        """Verify grant() correctly handles Folder as subject."""
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Parent", owner=owner)
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()

        document.grant(folder, "parent")

        write = recording_adapter_instance.writes[0]
        assert write.key.object == f"document:{document.pk}"
        assert write.key.relation == "parent"
        assert write.key.subject == f"folder:{folder.pk}"

    def test_revoke_folder_as_subject_from_document(self, recording_adapter_instance):
        """Verify revoke() correctly handles Folder as subject."""
        owner = User.objects.create_user(username="owner", password="pass")
        folder = Folder.objects.create(name="Parent", owner=owner)
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.deletes.clear()

        document.revoke(folder, "parent")

        delete = recording_adapter_instance.deletes[0]
        assert delete.object == f"document:{document.pk}"
        assert delete.relation == "parent"
        assert delete.subject == f"folder:{folder.pk}"

    def test_grant_workspace_as_subject_to_document(self, recording_adapter_instance):
        """Verify grant() correctly handles Workspace as subject."""
        owner = User.objects.create_user(username="owner", password="pass")
        workspace = Workspace.objects.create(name="Test Workspace")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.writes.clear()

        document.grant(workspace, "collaborator")

        write = recording_adapter_instance.writes[0]
        assert write.key.object == f"document:{document.pk}"
        assert write.key.relation == "collaborator"
        assert write.key.subject == f"workspace:{workspace.pk}"


@pytest.mark.django_db
class TestGrantRevokePreservesOtherData:
    """Test that grant/revoke don't affect the model instance itself."""

    def test_grant_does_not_modify_model_state(self, recording_adapter_instance):
        """Verify grant() doesn't change the document object's attributes."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Original Title", owner=owner)

        original_title = document.title
        original_owner_id = document.owner_id

        document.grant(member, "editor")

        # Model attributes should be unchanged
        assert document.title == original_title
        assert document.owner_id == original_owner_id

    def test_revoke_does_not_modify_model_state(self, recording_adapter_instance):
        """Verify revoke() doesn't change the document object's attributes."""
        owner = User.objects.create_user(username="owner", password="pass")
        member = User.objects.create_user(username="member", password="pass")
        document = Document.objects.create(title="Original Title", owner=owner)

        original_title = document.title
        original_owner_id = document.owner_id

        document.revoke(member, "editor")

        # Model attributes should be unchanged
        assert document.title == original_title
        assert document.owner_id == original_owner_id


@pytest.mark.django_db
class TestHasPermIntegration:
    """Integration tests for has_perm() with realistic scenarios."""

    def test_has_perm_owner_check(self, recording_adapter_instance):
        """Test has_perm with owner scenario."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        assert document.has_perm(owner, "view") is True

    def test_has_perm_permission_denied_scenario(self, recording_adapter_instance):
        """Test has_perm with permission denied scenario."""
        owner = User.objects.create_user(username="owner", password="pass")
        other = User.objects.create_user(username="other", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        # Default is False (not set)
        recording_adapter_instance.set_check_response(
            subject=f"user:{other.pk}",
            relation="edit",
            object_ref=f"document:{document.pk}",
            result=False,
        )

        assert document.has_perm(other, "edit") is False

    def test_has_perm_with_context_passed_to_adapter(self, recording_adapter_instance):
        """Verify has_perm() passes through to adapter.check() correctly."""
        owner = User.objects.create_user(username="owner", password="pass")
        document = Document.objects.create(title="Test", owner=owner)

        recording_adapter_instance.set_check_response(
            subject=f"user:{owner.pk}",
            relation="view",
            object_ref=f"document:{document.pk}",
            result=True,
        )

        # Call has_perm - it should internally call adapter.check
        result = document.has_perm(owner, "view")

        # Verify adapter.check_calls was recorded
        assert len(recording_adapter_instance.check_calls) >= 1
        assert result is True
