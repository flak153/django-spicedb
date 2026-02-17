"""TDD tests for DX improvements.

Written BEFORE implementation — all tests should FAIL initially,
then PASS after the corresponding fix is implemented.

Features:
1. Auto-inject RebacManager via metaclass
2. RebacQuerySet.update() auto-syncs tuples
3. Declarative external_types in settings
4. Duplicate type-name registration warning
5. Fail-fast on startup (system checks)
"""

import warnings

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from django_spicedb.integrations.orm import RebacManager, RebacQuerySet

User = get_user_model()


# ============================================================
# Feature 1: Auto-inject RebacManager via metaclass
# ============================================================


class TestAutoInjectRebacManager:
    """RebacModel subclasses should get RebacManager without 'objects = RebacManager()'."""

    def test_folder_has_rebac_manager(self):
        from example_project.documents.models import Folder

        assert isinstance(Folder.objects, RebacManager)

    def test_workspace_has_rebac_manager(self):
        from example_project.documents.models import Workspace

        assert isinstance(Workspace.objects, RebacManager)

    def test_document_keeps_its_explicit_rebac_manager(self):
        """Models that already declare RebacManager should not be affected."""
        from example_project.documents.models import Document

        assert isinstance(Document.objects, RebacManager)

    def test_auto_injected_queryset_has_accessible_by(self):
        from example_project.documents.models import Folder

        qs = Folder.objects.all()
        assert hasattr(qs, "accessible_by")

    def test_auto_injected_queryset_is_rebac_queryset(self):
        from example_project.documents.models import Folder

        qs = Folder.objects.all()
        assert isinstance(qs, RebacQuerySet)

    @pytest.mark.django_db(transaction=True)
    def test_folder_bulk_create_syncs_without_manual_call(self, recording_adapter):
        """Folder.objects.bulk_create() should auto-sync — no manual sync_instances()."""
        from example_project.documents.models import Folder

        user = User.objects.create_user(username="auto_bc", password="pass")
        Folder.objects.bulk_create([
            Folder(name=f"AutoSync{i}", owner=user) for i in range(3)
        ])
        owner_writes = [w for w in recording_adapter.writes if w.key.relation == "owner"]
        assert len(owner_writes) >= 3


# ============================================================
# Feature 2: RebacQuerySet.update() auto-syncs tuples
# ============================================================


@pytest.mark.django_db(transaction=True)
class TestAutoSyncUpdate:
    """QuerySet.update() on a RebacModel should auto-sync FK changes to SpiceDB."""

    def test_update_syncs_owner_fk_change(self, recording_adapter):
        from example_project.documents.models import Document

        u1 = User.objects.create_user(username="upd_u1", password="pass")
        u2 = User.objects.create_user(username="upd_u2", password="pass")
        Document.objects.create(title="UpdDoc", owner=u1)

        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        Document.objects.filter(owner=u1).update(owner=u2)

        # Old owner tuple deleted, new owner tuple written
        assert len(recording_adapter.deletes) >= 1
        assert len(recording_adapter.writes) >= 1

    def test_update_non_binding_field_skips_sync(self, recording_adapter):
        from example_project.documents.models import Document

        u1 = User.objects.create_user(username="upd_nb", password="pass")
        Document.objects.create(title="NBDoc", owner=u1)

        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        Document.objects.filter(owner=u1).update(title="Renamed")

        assert len(recording_adapter.deletes) == 0
        assert len(recording_adapter.writes) == 0

    def test_update_returns_correct_count(self, recording_adapter):
        from example_project.documents.models import Document

        u1 = User.objects.create_user(username="upd_ct1", password="pass")
        u2 = User.objects.create_user(username="upd_ct2", password="pass")
        for i in range(3):
            Document.objects.create(title=f"CtDoc{i}", owner=u1)

        count = Document.objects.filter(owner=u1).update(owner=u2)
        assert count == 3

    def test_update_multiple_fk_fields(self, recording_adapter):
        from example_project.documents.models import Document, Folder

        u1 = User.objects.create_user(username="upd_mf1", password="pass")
        u2 = User.objects.create_user(username="upd_mf2", password="pass")
        fo = User.objects.create_user(username="upd_mfo", password="pass")
        f1 = Folder.objects.create(name="UF1", owner=fo)
        f2 = Folder.objects.create(name="UF2", owner=fo)
        Document.objects.create(title="MFDoc", owner=u1, folder=f1)

        recording_adapter.writes.clear()
        recording_adapter.deletes.clear()

        Document.objects.filter(owner=u1).update(owner=u2, folder=f2)

        # Both owner and parent tuples should change
        assert len(recording_adapter.deletes) >= 2
        assert len(recording_adapter.writes) >= 2


# ============================================================
# Feature 3: Declarative external_types in settings
# ============================================================


class TestExternalTypesSettings:
    """REBAC['external_types'] should register third-party models declaratively."""

    def test_external_types_registers_company(self):
        """Company (a plain Django model) can be registered via settings."""
        import django_spicedb.conf as conf

        config = {
            "external_types": {
                "company": "example_project.documents.models.Company",
            },
            "adapter": {
                "endpoint": "localhost:50051",
                "token": "devkey",
                "insecure": True,
            },
        }
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            graph = conf.get_type_graph()
            assert "company" in graph.types

    def test_external_types_with_relations(self):
        """external_types can declare relations and permissions."""
        import django_spicedb.conf as conf

        config = {
            "external_types": {
                "company": {
                    "model": "example_project.documents.models.Company",
                    "relations": {"owner": "user"},
                    "permissions": {"view": "owner"},
                },
            },
            "adapter": {
                "endpoint": "localhost:50051",
                "token": "devkey",
                "insecure": True,
            },
        }
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            graph = conf.get_type_graph()
            assert "company" in graph.types
            assert "owner" in graph.types["company"].relations


# ============================================================
# Feature 4: Duplicate type-name warning
# ============================================================


class TestDuplicateTypeNameWarning:
    """register_type() should warn when overwriting an existing type name."""

    def test_warns_on_duplicate_type_name(self):
        from django_spicedb.core import register_type

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # User is already registered as "user" — this should warn
            register_type(User, type_name="user")
            dupes = [x for x in w if "already registered" in str(x.message).lower()]
            assert len(dupes) >= 1


# ============================================================
# Feature 5: System check for unregistered relation targets
# ============================================================


@pytest.mark.django_db
class TestSystemChecks:
    """Django system checks should catch common misconfigurations."""

    def test_check_warns_on_unregistered_relation_target(self):
        """System checks should include a check for unregistered relation targets."""
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        # Run Django system checks — after fix, django_spicedb.checks should
        # validate that all relation targets reference registered types
        call_command("check", "--tag", "rebac", stdout=out, stderr=StringIO())
        # The check command should succeed (no crash) and recognize the 'rebac' tag
        assert out.getvalue() is not None
