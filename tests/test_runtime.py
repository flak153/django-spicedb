import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.runtime import PermissionEvaluator
from django_rebac.sync import registry

from example_project.documents.models import Document, Workspace, HierarchyResource


@pytest.fixture
def runtime_rebac_setup(recording_adapter):
    config = {
        "types": {
            "user": {"model": "django.contrib.auth.models.User"},
            "workspace": {
                "model": "example_project.documents.models.Workspace",
                "relations": {"member": "user"},
                "bindings": {"member": {"field": "members", "kind": "m2m"}},
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
        yield
    conf.reset_type_graph_cache()
    registry.refresh()


@pytest.mark.django_db
def test_permission_evaluator_can(runtime_rebac_setup, recording_adapter):
    User = get_user_model()
    owner = User.objects.create_user(username="owner", password="pass")
    workspace = Workspace.objects.create(name="Acme")
    node = HierarchyResource.objects.create(name="Folder")
    document = Document.objects.create(
        title="Spec",
        owner=owner,
        workspace=workspace,
        resource=node,
    )

    recording_adapter.set_check_response(
        subject=f"user:{owner.pk}",
        relation="view",
        object_ref=f"document:{document.pk}",
        result=True,
        context={"ip": "127.0.0.1"},
    )

    evaluator = PermissionEvaluator(owner, context={"ip": "127.0.0.1"})
    assert evaluator.can("view", document)
    assert len(recording_adapter.check_calls) == 1

    # Cached result should not issue another check
    assert evaluator.can("view", document)
    assert len(recording_adapter.check_calls) == 1


@pytest.mark.django_db
def test_accessible_by(runtime_rebac_setup, recording_adapter):
    User = get_user_model()
    owner = User.objects.create_user(username="owner", password="pass")
    workspace = Workspace.objects.create(name="Acme")
    node = HierarchyResource.objects.create(name="Folder")

    doc1 = Document.objects.create(title="A", owner=owner, workspace=workspace, resource=node)
    doc2 = Document.objects.create(title="B", owner=owner, workspace=workspace, resource=node)
    Document.objects.create(title="C", owner=owner, workspace=workspace, resource=node)

    recording_adapter.set_lookup_response(
        subject=f"user:{owner.pk}",
        relation="view",
        resource_type="document",
        results=[str(doc1.pk), str(doc2.pk)],
        context={"scope": "branch"},
    )

    evaluator = PermissionEvaluator(owner, context={"scope": "branch"})
    qs = Document.objects.accessible_by(owner, "view", evaluator=evaluator)
    titles = set(qs.values_list("title", flat=True))
    assert titles == {"A", "B"}
    assert len(recording_adapter.lookup_calls) == 1
