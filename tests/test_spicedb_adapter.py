import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.adapters import factory
from django_rebac.adapters.base import TupleKey, TupleWrite
from django_rebac.runtime import PermissionEvaluator
from django_rebac.schema import publish_schema
from django_rebac.sync import registry
from django_rebac.sync.backfill import backfill_tuples
from django_rebac.types import TypeGraph

from example_project.documents.models import HierarchyResource


def _test_graph() -> TypeGraph:
    return TypeGraph(
        {
            "user": {},
            "hierarchy_resource": {
                "relations": {
                    "parent": "hierarchy_resource",
                    "manager": "user",
                },
                "permissions": {
                    "manage": "manager + parent->manage",
                },
            },
            "document": {
                "relations": {
                    "owner": "user",
                    "parent": "hierarchy_resource",
                },
                "permissions": {"view": "owner"},
            },
        }
    )


@pytest.fixture
def ensure_schema(spicedb_adapter):
    publish_schema(spicedb_adapter, graph=_test_graph())
    yield


def test_write_check_and_delete(spicedb_adapter, ensure_schema) -> None:
    doc_id = uuid.uuid4().hex
    user_id = uuid.uuid4().hex
    key = TupleKey(
        object=f"document:{doc_id}",
        relation="owner",
        subject=f"user:{user_id}",
    )

    spicedb_adapter.write_tuples([TupleWrite(key=key)])

    assert spicedb_adapter.check(
        subject=f"user:{user_id}",
        relation="view",
        object_=f"document:{doc_id}",
        consistency="fully_consistent",
    )

    resources = list(
        spicedb_adapter.lookup_resources(
            subject=f"user:{user_id}",
            relation="view",
            resource_type="document",
            consistency="fully_consistent",
        )
    )
    assert doc_id in resources

    spicedb_adapter.delete_tuples([key])
    assert not spicedb_adapter.check(
        subject=f"user:{user_id}",
        relation="view",
        object_=f"document:{doc_id}",
        consistency="fully_consistent",
    )


def test_backfill_batches(spicedb_adapter, ensure_schema) -> None:
    user_id = uuid.uuid4().hex
    keys = [
        TupleWrite(
            key=TupleKey(
                object=f"document:{uuid.uuid4().hex}",
                relation="owner",
                subject=f"user:{user_id}",
            )
        )
        for _ in range(3)
    ]

    count = backfill_tuples(spicedb_adapter, keys, batch_size=2)
    assert count == len(keys)

    resources = list(
        spicedb_adapter.lookup_resources(
            subject=f"user:{user_id}",
            relation="view",
            resource_type="document",
            consistency="fully_consistent",
        )
    )
    # lookup returns object ids
    assert {key.key.object.split(":", 1)[1] for key in keys}.issubset(set(resources))


@pytest.mark.django_db
def test_hierarchy_manage_permission(spicedb_adapter) -> None:
    adapter = spicedb_adapter
    factory.set_adapter(adapter)

    config = {
        "types": {
            "user": {"model": "django.contrib.auth.models.User"},
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
                "relations": {
                    "owner": "user",
                },
            },
        },
        "db_overrides": False,
    }

    try:
        with override_settings(REBAC=config):
            conf.reset_type_graph_cache()
            registry.refresh()
            publish_schema(adapter, graph=conf.get_type_graph())

            User = get_user_model()
            manager = User.objects.create_user(username="manager", password="pass")
            stranger = User.objects.create_user(username="other", password="pass")

            root = HierarchyResource.objects.create(name="Bank")
            child = HierarchyResource.objects.create(name="Branch", parent=root)
            root.managers.add(manager)

            def can_manage(user, node):
                return adapter.check(
                    subject=f"user:{user.pk}",
                    relation="manage",
                    object_=f"hierarchy_resource:{node.pk}",
                    consistency="fully_consistent",
                )

            assert can_manage(manager, root)
            assert can_manage(manager, child)
            assert not can_manage(stranger, child)

            evaluator = PermissionEvaluator(manager)
            managed_ids = set(
                HierarchyResource.objects.accessible_by(
                    manager,
                    "manage",
                    consistency="fully_consistent",
                )
                .values_list("pk", flat=True)
            )
            assert managed_ids == {root.pk, child.pk}

            # Clean up tuples by deleting nodes
            child.delete()
            root.delete()
    finally:
        factory.reset_adapter()
        conf.reset_type_graph_cache()
        registry.refresh()
