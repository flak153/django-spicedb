import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.sync import registry

from example_project.documents.models import Document, Workspace, HierarchyResource


@pytest.fixture
def document_rebac_setup(recording_adapter):
    config = {
        "types": {
            "user": {
                "model": "django.contrib.auth.models.User",
            },
            "workspace": {
                "model": "example_project.documents.models.Workspace",
                "relations": {
                    "member": "user",
                },
                "bindings": {
                    "member": {"field": "members", "kind": "m2m"},
                },
            },
            "hierarchy_resource": {
                "model": "example_project.documents.models.HierarchyResource",
                "relations": {
                    "parent": "hierarchy_resource",
                    "manager": "user",
                },
                "permissions": {
                    "manage": "manager + parent->manage",
                },
                "bindings": {
                    "parent": {"field": "parent", "kind": "fk"},
                    "manager": {"field": "managers", "kind": "m2m"},
                },
            },
            "document": {
                "model": "example_project.documents.models.Document",
                "relations": {
                    "owner": "user",
                    "parent": "hierarchy_resource",
                },
                "bindings": {
                    "owner": {"field": "owner", "kind": "fk"},
                    "parent": {"field": "resource", "kind": "fk"},
                },
            },
        },
        "db_overrides": False,
    }
    with override_settings(REBAC=config):
        conf.reset_type_graph_cache()
        registry.refresh()
        assert "hierarchy_resource" in conf.get_type_graph().types
        yield
    conf.reset_type_graph_cache()
    registry.refresh()


@pytest.mark.django_db
def test_fk_and_m2m_bindings(document_rebac_setup, recording_adapter):

    User = get_user_model()
    owner = User.objects.create_user(username="owner", password="pass")
    member = User.objects.create_user(username="member", password="pass")

    workspace = Workspace.objects.create(name="Acme")
    workspace.members.add(member)

    root = HierarchyResource.objects.create(name="Root")
    child = HierarchyResource.objects.create(name="Child", parent=root)

    document = Document.objects.create(
        title="Spec",
        owner=owner,
        workspace=workspace,
        resource=child,
    )

    root.managers.add(owner)

    write_tuples = {
        (w.key.object, w.key.relation, w.key.subject)
        for w in recording_adapter.writes
    }

    assert (
        f"workspace:{workspace.pk}",
        "member",
        f"user:{member.pk}",
    ) in write_tuples

    assert (
        f"document:{document.pk}",
        "owner",
        f"user:{owner.pk}",
    ) in write_tuples

    assert (
        f"document:{document.pk}",
        "parent",
        f"hierarchy_resource:{child.pk}",
    ) in write_tuples

    assert (
        f"hierarchy_resource:{root.pk}",
        "manager",
        f"user:{owner.pk}",
    ) in write_tuples

    assert (
        f"hierarchy_resource:{child.pk}",
        "parent",
        f"hierarchy_resource:{root.pk}",
    ) in write_tuples

    child_pk = child.pk
    root_pk = root.pk
    child.delete()
    delete_tuples = {
        (d.object, d.relation, d.subject)
        for d in recording_adapter.deletes
    }
    assert (
        f"hierarchy_resource:{child_pk}",
        "parent",
        f"hierarchy_resource:{root_pk}",
    ) in delete_tuples

    # Removing member should delete tuple
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
