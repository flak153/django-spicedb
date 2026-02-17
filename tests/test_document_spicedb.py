"""
End-to-end tests for Document/Folder/Workspace models with real SpiceDB.

Covers: FK permissions, self-referential folder hierarchy, document-folder chain
operations, M2M workspace bindings, bulk operations, reconciliation, and FK
change tracking.
"""

import pytest
from django.contrib.auth import get_user_model

import django_spicedb.conf as conf
from django_spicedb.adapters import factory
from django_spicedb.sync import registry
from django_spicedb.sync.registry import sync_queryset_update

from example_project.documents.models import Document, Folder, Workspace

User = get_user_model()

CONSISTENCY = "fully_consistent"


@pytest.fixture
def clean_doc_spicedb(spicedb_adapter):
    """Set up adapter, publish schema, and clean up after each test."""
    factory.set_adapter(spicedb_adapter)
    conf.reset_type_graph_cache()
    registry.refresh()

    graph = conf.get_type_graph()
    spicedb_adapter.publish_schema(graph.compile_schema())

    yield spicedb_adapter

    try:
        for t in ("document", "folder", "workspace"):
            spicedb_adapter.delete_all_relationships(t)
    except Exception:
        pass
    finally:
        factory.reset_adapter()


def _check(adapter, user, permission, type_name, obj):
    return adapter.check(
        subject=f"user:{user.pk}",
        relation=permission,
        object_=f"{type_name}:{obj.pk}",
        consistency=CONSISTENCY,
    )


def _lookup(adapter, user, permission, type_name):
    return set(
        adapter.lookup_resources(
            subject=f"user:{user.pk}",
            relation=permission,
            resource_type=type_name,
            consistency=CONSISTENCY,
        )
    )


# ---------------------------------------------------------------------------
# Class 1: Schema Publishing
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestSchemaPublishing:

    def test_schema_includes_document_folder_workspace(self, clean_doc_spicedb):
        graph = conf.get_type_graph()
        schema = graph.compile_schema()

        assert "definition document" in schema
        assert "definition folder" in schema
        assert "definition workspace" in schema

        # Document relations
        assert "relation owner: user" in schema
        assert "relation parent: folder" in schema

        # Folder relations
        assert "relation parent: folder" in schema

        # Workspace relations
        assert "relation member: user" in schema


# ---------------------------------------------------------------------------
# Class 2: Basic FK Permissions
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestBasicFKPermissions:

    def test_document_owner_has_view_and_edit(self, clean_doc_spicedb):
        user = User.objects.create_user(username="doc_owner1", password="pass")
        doc = Document.objects.create(title="Doc1", owner=user)

        assert _check(clean_doc_spicedb, user, "view", "document", doc)
        assert _check(clean_doc_spicedb, user, "edit", "document", doc)

    def test_non_owner_cannot_access_document(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="doc_u1", password="pass")
        u2 = User.objects.create_user(username="doc_u2", password="pass")
        doc = Document.objects.create(title="Doc2", owner=u1)

        assert not _check(clean_doc_spicedb, u2, "view", "document", doc)
        assert not _check(clean_doc_spicedb, u2, "edit", "document", doc)

    def test_document_inherits_view_from_folder_owner(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="folder_owner", password="pass")
        u2 = User.objects.create_user(username="doc_owner_fk", password="pass")
        folder = Folder.objects.create(name="F1", owner=u1)
        doc = Document.objects.create(title="Doc3", owner=u2, folder=folder)

        # u1 (folder owner) can view/edit doc via parent->view/edit
        assert _check(clean_doc_spicedb, u1, "view", "document", doc)
        assert _check(clean_doc_spicedb, u1, "edit", "document", doc)

        # u2 (doc owner) can also view/edit
        assert _check(clean_doc_spicedb, u2, "view", "document", doc)
        assert _check(clean_doc_spicedb, u2, "edit", "document", doc)

    def test_document_without_folder_owner_only(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="solo_owner", password="pass")
        u2 = User.objects.create_user(username="stranger1", password="pass")
        doc = Document.objects.create(title="Doc4", owner=u1, folder=None)

        assert _check(clean_doc_spicedb, u1, "view", "document", doc)
        assert not _check(clean_doc_spicedb, u2, "view", "document", doc)

    def test_folder_owner_has_view_and_edit(self, clean_doc_spicedb):
        user = User.objects.create_user(username="fld_owner", password="pass")
        folder = Folder.objects.create(name="F2", owner=user)

        assert _check(clean_doc_spicedb, user, "view", "folder", folder)
        assert _check(clean_doc_spicedb, user, "edit", "folder", folder)


# ---------------------------------------------------------------------------
# Class 3: Self-Referential Folder Hierarchy
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestSelfReferentialFolderHierarchy:

    def test_two_level_folder_inheritance(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="root_owner", password="pass")
        u2 = User.objects.create_user(username="child_owner", password="pass")

        root = Folder.objects.create(name="Root", owner=u1)
        child = Folder.objects.create(name="Child", owner=u2, parent=root)

        # u1 (root owner) can view child via parent->view
        assert _check(clean_doc_spicedb, u1, "view", "folder", child)
        # u2 (child owner) can view child directly
        assert _check(clean_doc_spicedb, u2, "view", "folder", child)

    def test_three_level_folder_inheritance(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="l1_owner", password="pass")
        u2 = User.objects.create_user(username="l2_owner", password="pass")
        u3 = User.objects.create_user(username="l3_owner", password="pass")

        root = Folder.objects.create(name="L1", owner=u1)
        mid = Folder.objects.create(name="L2", owner=u2, parent=root)
        leaf = Folder.objects.create(name="L3", owner=u3, parent=mid)

        # Root owner can view the leaf (2 levels deep)
        assert _check(clean_doc_spicedb, u1, "view", "folder", leaf)
        # Mid owner can view leaf (1 level deep)
        assert _check(clean_doc_spicedb, u2, "view", "folder", leaf)
        # Leaf owner can view leaf directly
        assert _check(clean_doc_spicedb, u3, "view", "folder", leaf)

    def test_five_level_document_chain(self, clean_doc_spicedb):
        users = [
            User.objects.create_user(username=f"chain_u{i}", password="pass")
            for i in range(5)
        ]
        doc_owner = User.objects.create_user(username="chain_doc_owner", password="pass")

        # Build 4-level folder chain
        folders = []
        for i, u in enumerate(users[:4]):
            parent = folders[-1] if folders else None
            folders.append(Folder.objects.create(name=f"Chain{i}", owner=u, parent=parent))

        # Doc at bottom of chain
        doc = Document.objects.create(title="DeepDoc", owner=doc_owner, folder=folders[-1])

        # All 4 folder owners can view the doc via ancestor chain
        for u in users[:4]:
            assert _check(clean_doc_spicedb, u, "view", "document", doc), \
                f"User {u.username} should view doc"

        # Doc owner can view it too
        assert _check(clean_doc_spicedb, doc_owner, "view", "document", doc)

        # Unrelated user cannot
        assert not _check(clean_doc_spicedb, users[4], "view", "document", doc)

    def test_lookup_resources_traverses_hierarchy(self, clean_doc_spicedb):
        user = User.objects.create_user(username="lookup_hier", password="pass")
        other = User.objects.create_user(username="lookup_other", password="pass")

        root = Folder.objects.create(name="LRoot", owner=user)
        c1 = Folder.objects.create(name="LC1", owner=other, parent=root)
        c2 = Folder.objects.create(name="LC2", owner=other, parent=c1)
        c3 = Folder.objects.create(name="LC3", owner=other, parent=c2)

        ids = _lookup(clean_doc_spicedb, user, "view", "folder")
        for f in [root, c1, c2, c3]:
            assert str(f.pk) in ids, f"Folder {f.name} should be visible"


# ---------------------------------------------------------------------------
# Class 4: Document-Folder Chain Operations
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDocumentFolderChain:

    def test_document_move_between_folders(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="mv_u1", password="pass")
        u2 = User.objects.create_user(username="mv_u2", password="pass")
        doc_owner = User.objects.create_user(username="mv_doc_owner", password="pass")

        f1 = Folder.objects.create(name="MoveF1", owner=u1)
        f2 = Folder.objects.create(name="MoveF2", owner=u2)
        doc = Document.objects.create(title="MoveDoc", owner=doc_owner, folder=f1)

        # Initially u1 can view, u2 cannot
        assert _check(clean_doc_spicedb, u1, "view", "document", doc)
        assert not _check(clean_doc_spicedb, u2, "view", "document", doc)

        # Move doc to f2
        doc.folder = f2
        doc.save()

        # Now u2 can view, u1 cannot
        assert not _check(clean_doc_spicedb, u1, "view", "document", doc)
        assert _check(clean_doc_spicedb, u2, "view", "document", doc)

    def test_document_owner_change(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="oc_u1", password="pass")
        u2 = User.objects.create_user(username="oc_u2", password="pass")
        folder_owner = User.objects.create_user(username="oc_fowner", password="pass")

        folder = Folder.objects.create(name="OCFolder", owner=folder_owner)
        doc = Document.objects.create(title="OCDoc", owner=u1, folder=folder)

        assert _check(clean_doc_spicedb, u1, "view", "document", doc)

        # Change owner
        doc.owner = u2
        doc.save()

        # u1 loses owner access, u2 gains it
        assert not _check(clean_doc_spicedb, u1, "edit", "document", doc)
        assert _check(clean_doc_spicedb, u2, "edit", "document", doc)
        # folder_owner retains parent access
        assert _check(clean_doc_spicedb, folder_owner, "view", "document", doc)

    def test_accessible_by_returns_correct_documents(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="ab_u1", password="pass")
        u2 = User.objects.create_user(username="ab_u2", password="pass")

        f1 = Folder.objects.create(name="ABF1", owner=u1)
        f2 = Folder.objects.create(name="ABF2", owner=u2)

        docs_f1 = [
            Document.objects.create(title=f"ABDoc1_{i}", owner=u1, folder=f1)
            for i in range(3)
        ]
        docs_f2 = [
            Document.objects.create(title=f"ABDoc2_{i}", owner=u2, folder=f2)
            for i in range(3)
        ]

        # u1 should see docs in f1 (as owner + folder owner)
        accessible = set(
            Document.objects.accessible_by(
                u1, "view", consistency=CONSISTENCY
            ).values_list("pk", flat=True)
        )
        for d in docs_f1:
            assert d.pk in accessible
        for d in docs_f2:
            assert d.pk not in accessible

    def test_folder_deletion_cascades(self, clean_doc_spicedb):
        user = User.objects.create_user(username="del_u", password="pass")
        folder = Folder.objects.create(name="DelFolder", owner=user)
        docs = [
            Document.objects.create(title=f"DelDoc{i}", owner=user, folder=folder)
            for i in range(3)
        ]

        doc_pks = [str(d.pk) for d in docs]

        # Verify docs are accessible
        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for pk in doc_pks:
            assert pk in ids

        # Delete folder (cascades to docs in Django)
        folder.delete()

        # After cascade, documents are deleted too - lookup should not return them
        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for pk in doc_pks:
            assert pk not in ids


# ---------------------------------------------------------------------------
# Class 5: Workspace M2M Binding
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestWorkspaceM2MBinding:

    def test_member_has_view_permission(self, clean_doc_spicedb):
        user = User.objects.create_user(username="ws_member", password="pass")
        ws = Workspace.objects.create(name="WS1")
        ws.members.add(user)

        assert _check(clean_doc_spicedb, user, "view", "workspace", ws)

    def test_member_removal_revokes_access(self, clean_doc_spicedb):
        user = User.objects.create_user(username="ws_remove", password="pass")
        ws = Workspace.objects.create(name="WS2")
        ws.members.add(user)

        assert _check(clean_doc_spicedb, user, "view", "workspace", ws)

        ws.members.remove(user)

        assert not _check(clean_doc_spicedb, user, "view", "workspace", ws)

    def test_members_set_replaces_all(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="ws_set1", password="pass")
        u2 = User.objects.create_user(username="ws_set2", password="pass")
        u3 = User.objects.create_user(username="ws_set3", password="pass")
        u4 = User.objects.create_user(username="ws_set4", password="pass")

        ws = Workspace.objects.create(name="WS3")
        ws.members.set([u1, u2])

        assert _check(clean_doc_spicedb, u1, "view", "workspace", ws)
        assert _check(clean_doc_spicedb, u2, "view", "workspace", ws)

        # Replace members
        ws.members.set([u3, u4])

        assert not _check(clean_doc_spicedb, u1, "view", "workspace", ws)
        assert not _check(clean_doc_spicedb, u2, "view", "workspace", ws)
        assert _check(clean_doc_spicedb, u3, "view", "workspace", ws)
        assert _check(clean_doc_spicedb, u4, "view", "workspace", ws)

    def test_lookup_resources_returns_member_workspaces(self, clean_doc_spicedb):
        user = User.objects.create_user(username="ws_lookup", password="pass")

        ws1 = Workspace.objects.create(name="WSL1")
        ws2 = Workspace.objects.create(name="WSL2")
        ws3 = Workspace.objects.create(name="WSL3")

        ws1.members.add(user)
        ws2.members.add(user)
        # ws3: user is NOT a member

        ids = _lookup(clean_doc_spicedb, user, "view", "workspace")
        assert str(ws1.pk) in ids
        assert str(ws2.pk) in ids
        assert str(ws3.pk) not in ids


# ---------------------------------------------------------------------------
# Class 6: Bulk Operations
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestBulkOperations:

    def test_document_bulk_create_syncs_tuples(self, clean_doc_spicedb):
        user = User.objects.create_user(username="bulk_owner", password="pass")
        docs = Document.objects.bulk_create([
            Document(title=f"BulkDoc{i}", owner=user)
            for i in range(10)
        ])

        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for d in docs:
            assert str(d.pk) in ids, f"BulkDoc {d.pk} should be visible"

    def test_folder_bulk_create_with_parent(self, clean_doc_spicedb):
        root_owner = User.objects.create_user(username="bulk_root", password="pass")
        child_owner = User.objects.create_user(username="bulk_child", password="pass")

        root = Folder.objects.create(name="BulkRoot", owner=root_owner)
        # Folder inherits RebacManager from RebacModel, so bulk_create auto-syncs
        children = Folder.objects.bulk_create([
            Folder(name=f"BulkChild{i}", owner=child_owner, parent=root)
            for i in range(5)
        ])

        # Root owner can view all children via parent->view
        for c in children:
            assert _check(clean_doc_spicedb, root_owner, "view", "folder", c), \
                f"Root owner should view {c.name}"

    def test_sync_queryset_update_owner_change(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="squ_u1", password="pass")
        u2 = User.objects.create_user(username="squ_u2", password="pass")

        docs = Document.objects.bulk_create([
            Document(title=f"SQUDoc{i}", owner=u1)
            for i in range(5)
        ])

        # Verify u1 owns all
        ids = _lookup(clean_doc_spicedb, u1, "view", "document")
        for d in docs:
            assert str(d.pk) in ids

        # Bulk update owner
        qs = Document.objects.filter(pk__in=[d.pk for d in docs])
        sync_queryset_update(qs, owner=u2)

        # u1 loses, u2 gains
        ids_u1 = _lookup(clean_doc_spicedb, u1, "view", "document")
        ids_u2 = _lookup(clean_doc_spicedb, u2, "view", "document")
        for d in docs:
            assert str(d.pk) not in ids_u1
            assert str(d.pk) in ids_u2

    def test_sync_queryset_update_folder_move(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="sqf_u1", password="pass")
        u2 = User.objects.create_user(username="sqf_u2", password="pass")
        doc_owner = User.objects.create_user(username="sqf_doc", password="pass")

        f1 = Folder.objects.create(name="SQF1", owner=u1)
        f2 = Folder.objects.create(name="SQF2", owner=u2)

        docs = Document.objects.bulk_create([
            Document(title=f"SQFDoc{i}", owner=doc_owner, folder=f1)
            for i in range(5)
        ])

        # u1 can view all via folder
        for d in docs:
            assert _check(clean_doc_spicedb, u1, "view", "document", d)

        # Move all docs to f2
        qs = Document.objects.filter(pk__in=[d.pk for d in docs])
        sync_queryset_update(qs, folder=f2)

        # u1 loses parent access, u2 gains it
        for d in docs:
            d.refresh_from_db()
            assert not _check(clean_doc_spicedb, u1, "view", "document", d)
            assert _check(clean_doc_spicedb, u2, "view", "document", d)


# ---------------------------------------------------------------------------
# Class 7: Reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestReconciliation:

    def test_reconcile_fixes_missing_tuples(self, clean_doc_spicedb):
        from django_spicedb.sync.reconcile import reconcile_type

        user = User.objects.create_user(username="recon_fix", password="pass")

        # Disconnect all signals so creates don't sync
        registry._disconnect_all()
        try:
            docs = [
                Document.objects.create(title=f"ReconDoc{i}", owner=user)
                for i in range(5)
            ]
        finally:
            registry.refresh()

        # Verify docs are NOT accessible (signals were off)
        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for d in docs:
            assert str(d.pk) not in ids

        # Reconcile with fix
        result = reconcile_type("document", fix=True, adapter=clean_doc_spicedb)
        assert result.to_write >= 5
        assert result.fixed is True

        # Now docs should be accessible
        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for d in docs:
            assert str(d.pk) in ids

    def test_reconcile_dry_run_no_writes(self, clean_doc_spicedb):
        from django_spicedb.sync.reconcile import reconcile_type

        user = User.objects.create_user(username="recon_dry", password="pass")

        registry._disconnect_all()
        try:
            docs = [
                Document.objects.create(title=f"DryDoc{i}", owner=user)
                for i in range(5)
            ]
        finally:
            registry.refresh()

        # Dry run (fix=False)
        result = reconcile_type("document", fix=False, adapter=clean_doc_spicedb)
        assert result.to_write >= 5
        assert result.fixed is False

        # Tuples NOT written
        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for d in docs:
            assert str(d.pk) not in ids

    def test_reconcile_idempotent_with_existing_tuples(self, clean_doc_spicedb):
        from django_spicedb.sync.reconcile import reconcile_type

        user = User.objects.create_user(username="recon_idem", password="pass")
        docs = [
            Document.objects.create(title=f"IdemDoc{i}", owner=user)
            for i in range(5)
        ]

        # Verify tuples already exist
        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for d in docs:
            assert str(d.pk) in ids

        # Reconcile (with fix=True) should be idempotent / no errors
        result = reconcile_type("document", fix=True, adapter=clean_doc_spicedb)
        assert result.expected >= 5

        # Still accessible
        ids = _lookup(clean_doc_spicedb, user, "view", "document")
        for d in docs:
            assert str(d.pk) in ids


# ---------------------------------------------------------------------------
# Class 8: FK Change Tracking
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestFKChangeTracking:

    def test_document_owner_reassignment(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="fk_u1", password="pass")
        u2 = User.objects.create_user(username="fk_u2", password="pass")

        doc = Document.objects.create(title="FKDoc1", owner=u1)
        assert _check(clean_doc_spicedb, u1, "view", "document", doc)

        doc.owner = u2
        doc.save()

        assert not _check(clean_doc_spicedb, u1, "edit", "document", doc)
        assert _check(clean_doc_spicedb, u2, "edit", "document", doc)

    def test_folder_parent_move(self, clean_doc_spicedb):
        root1_owner = User.objects.create_user(username="fk_r1", password="pass")
        root2_owner = User.objects.create_user(username="fk_r2", password="pass")
        child_owner = User.objects.create_user(username="fk_ch", password="pass")

        root1 = Folder.objects.create(name="FKRoot1", owner=root1_owner)
        root2 = Folder.objects.create(name="FKRoot2", owner=root2_owner)
        child = Folder.objects.create(name="FKChild", owner=child_owner, parent=root1)

        assert _check(clean_doc_spicedb, root1_owner, "view", "folder", child)
        assert not _check(clean_doc_spicedb, root2_owner, "view", "folder", child)

        child.parent = root2
        child.save()

        assert not _check(clean_doc_spicedb, root1_owner, "view", "folder", child)
        assert _check(clean_doc_spicedb, root2_owner, "view", "folder", child)

    def test_null_to_fk_transition(self, clean_doc_spicedb):
        folder_owner = User.objects.create_user(username="fk_null_fo", password="pass")
        doc_owner = User.objects.create_user(username="fk_null_do", password="pass")

        folder = Folder.objects.create(name="FKNullFolder", owner=folder_owner)
        doc = Document.objects.create(title="FKNullDoc", owner=doc_owner, folder=None)

        # folder_owner has no access via parent
        assert not _check(clean_doc_spicedb, folder_owner, "view", "document", doc)

        doc.folder = folder
        doc.save()

        # folder_owner now has access via parent->view
        assert _check(clean_doc_spicedb, folder_owner, "view", "document", doc)

    def test_fk_to_null_transition(self, clean_doc_spicedb):
        folder_owner = User.objects.create_user(username="fk_tonull_fo", password="pass")
        doc_owner = User.objects.create_user(username="fk_tonull_do", password="pass")

        folder = Folder.objects.create(name="FKToNullFolder", owner=folder_owner)
        doc = Document.objects.create(title="FKToNullDoc", owner=doc_owner, folder=folder)

        # folder_owner has access
        assert _check(clean_doc_spicedb, folder_owner, "view", "document", doc)

        doc.folder = None
        doc.save()

        # folder_owner loses access
        assert not _check(clean_doc_spicedb, folder_owner, "view", "document", doc)
        # doc_owner retains access
        assert _check(clean_doc_spicedb, doc_owner, "view", "document", doc)

    def test_multiple_fk_changes_one_save(self, clean_doc_spicedb):
        u1 = User.objects.create_user(username="multi_u1", password="pass")
        u2 = User.objects.create_user(username="multi_u2", password="pass")
        fo1 = User.objects.create_user(username="multi_fo1", password="pass")
        fo2 = User.objects.create_user(username="multi_fo2", password="pass")

        f1 = Folder.objects.create(name="MultiF1", owner=fo1)
        f2 = Folder.objects.create(name="MultiF2", owner=fo2)
        doc = Document.objects.create(title="MultiDoc", owner=u1, folder=f1)

        # Initial state
        assert _check(clean_doc_spicedb, u1, "edit", "document", doc)
        assert _check(clean_doc_spicedb, fo1, "view", "document", doc)

        # Change both FKs in one save
        doc.owner = u2
        doc.folder = f2
        doc.save()

        # Old tuples deleted, new tuples written
        assert not _check(clean_doc_spicedb, u1, "edit", "document", doc)
        assert not _check(clean_doc_spicedb, fo1, "view", "document", doc)
        assert _check(clean_doc_spicedb, u2, "edit", "document", doc)
        assert _check(clean_doc_spicedb, fo2, "view", "document", doc)
