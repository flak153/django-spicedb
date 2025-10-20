import uuid

import pytest

from django_rebac.adapters.base import TupleKey, TupleWrite
from django_rebac.schema import publish_schema
from django_rebac.sync.backfill import backfill_tuples
from django_rebac.types import TypeGraph


def _test_graph() -> TypeGraph:
    return TypeGraph(
        {
            "user": {},
            "document": {
                "relations": {"owner": "user"},
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
    )

    resources = list(
        spicedb_adapter.lookup_resources(
            subject=f"user:{user_id}",
            relation="view",
            resource_type="document",
        )
    )
    assert doc_id in resources

    spicedb_adapter.delete_tuples([key])
    assert not spicedb_adapter.check(
        subject=f"user:{user_id}",
        relation="view",
        object_=f"document:{doc_id}",
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
        )
    )
    # lookup returns object ids
    assert {key.key.object.split(":", 1)[1] for key in keys}.issubset(set(resources))
