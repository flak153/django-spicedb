import pytest

from django_rebac.types import TypeGraph
from django_rebac.types.graph import (
    InvalidPermissionExpression,
    TypeGraphError,
    UnknownParentError,
    UnknownRelationSubject,
)


def test_compile_schema_with_parents_and_bindings() -> None:
    graph = TypeGraph(
        {
            "user": {},
            "workspace": {
                "relations": {"member": "user"},
                "permissions": {"view": "member"},
            },
            "document": {
                "relations": {
                    "owner": "user",
                    "viewer": "workspace#member",
                    "parent": "workspace",
                },
                "permissions": {
                    "view": "owner | viewer | parent->view",
                    "edit": "owner",
                },
                "parents": ["workspace"],
                "bindings": {
                    "owner": {"field": "owner", "kind": "fk"},
                    "viewer": {"field": "members", "kind": "m2m"},
                    "parent": {"field": "workspace", "kind": "fk"},
                },
            },
        }
    )

    schema = graph.compile_schema()

    assert "type document" in schema
    assert "define owner: user" in schema
    assert "define viewer: workspace#member" in schema
    assert "define view: owner | viewer | parent->view" in schema
    assert "parents\n    workspace" in schema

    bindings = graph.types["document"].bindings
    assert bindings["owner"]["field"] == "owner"
    assert bindings["viewer"]["kind"] == "m2m"


def test_parent_validation() -> None:
    with pytest.raises(UnknownParentError):
        TypeGraph(
            {
                "user": {},
                "document": {"parents": ["folder"]},
            }
        )


def test_relation_subject_validation() -> None:
    with pytest.raises(UnknownRelationSubject):
        TypeGraph(
            {
                "user": {},
                "document": {
                    "relations": {"owner": "account"},
                },
            }
        )


def test_permission_expression_validation() -> None:
    with pytest.raises(InvalidPermissionExpression):
        TypeGraph(
            {
                "user": {},
                "document": {
                    "relations": {"owner": "user"},
                    "permissions": {"view": "member"},
                },
            }
        )


def test_parent_cycle_detection() -> None:
    with pytest.raises(TypeGraphError):
        TypeGraph(
            {
                "a": {"parents": ["b"]},
                "b": {"parents": ["a"]},
            }
        )


def test_binding_validation_unknown_relation() -> None:
    with pytest.raises(TypeGraphError):
        TypeGraph(
            {
                "user": {},
                "document": {
                    "bindings": {"missing": {"field": "owner", "kind": "fk"}},
                },
            }
        )


def test_binding_validation_invalid_kind() -> None:
    with pytest.raises(TypeGraphError):
        TypeGraph(
            {
                "user": {},
                "document": {
                    "relations": {"owner": "user"},
                    "bindings": {"owner": {"field": "owner", "kind": "unknown"}},
                },
            }
        )
