import hashlib

import pytest
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.adapters.fake import FakeAdapter
from django_rebac.schema import compile_schema, publish_schema
from django_rebac.types import TypeGraph


@pytest.fixture(autouse=True)
def reset_cache():
    conf.reset_type_graph_cache()
    yield
    conf.reset_type_graph_cache()


def test_compile_schema_hashes_graph() -> None:
    graph = TypeGraph(
        {
            "user": {},
            "doc": {
                "relations": {"owner": "user"},
                "permissions": {"view": "owner"},
            },
        }
    )

    schema, digest = compile_schema(graph)

    assert schema.startswith("type doc")
    assert digest == hashlib.sha256(schema.encode("utf-8")).hexdigest()


@override_settings(
    REBAC={
        "types": {
            "user": {},
            "doc": {
                "relations": {"owner": "user"},
                "permissions": {"view": "owner"},
            },
        }
    }
)
def test_publish_schema_uses_adapter() -> None:
    adapter = FakeAdapter()

    digest = publish_schema(adapter)

    assert adapter.published_schemas
    assert len(adapter.published_schemas[-1]) > 0
    assert len(digest) == 64
