import unittest

from django_rebac.types import TypeGraph
from django_rebac.types.graph import (
    InvalidPermissionExpression,
    UnknownParentError,
    UnknownRelationSubject,
)


class TypeGraphTests(unittest.TestCase):
    def test_compile_minimal_schema(self) -> None:
        graph = TypeGraph(
            {
                "user": {},
                "document": {
                    "relations": {
                        "owner": "user",
                        "viewer": "user",
                    },
                    "permissions": {
                        "view": "owner | viewer",
                        "edit": "owner",
                    },
                },
            }
        )

        schema = graph.compile_schema()

        self.assertIn("type document", schema)
        self.assertIn("define owner: user", schema)
        self.assertIn("define view: owner | viewer", schema)

    def test_parent_validation(self) -> None:
        with self.assertRaises(UnknownParentError):
            TypeGraph(
                {
                    "user": {},
                    "document": {"parents": ["folder"]},
                }
            )

    def test_relation_subject_validation(self) -> None:
        with self.assertRaises(UnknownRelationSubject):
            TypeGraph(
                {
                    "user": {},
                    "document": {
                        "relations": {"owner": "account"},
                    },
                }
            )

    def test_permission_expression_validation(self) -> None:
        with self.assertRaises(InvalidPermissionExpression):
            TypeGraph(
                {
                    "user": {},
                    "document": {
                        "relations": {"owner": "user"},
                        "permissions": {"view": "member"},
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
