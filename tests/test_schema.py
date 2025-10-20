from django_rebac.schema import compile_schema
from django_rebac.types import TypeGraph


def test_compile_schema_returns_digest() -> None:
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
    assert len(digest) == 64
