"""In-memory adapter used for tests."""

from __future__ import annotations

import itertools
from typing import Any, Iterable, Mapping, Sequence

from .base import RebacAdapter, TupleKey, TupleWrite


class FakeAdapter(RebacAdapter):
    """Recording adapter that mimics SpiceDB behaviour for tests."""

    _schema_counter = itertools.count(1)

    def __init__(self) -> None:
        self.published_schemas: list[str] = []
        self.written_tuples: list[TupleWrite] = []
        self.deleted_tuples: list[TupleKey] = []

    def publish_schema(self, schema: str) -> str:
        self.published_schemas.append(schema)
        return f"fake-schema-{next(self._schema_counter)}"

    def write_tuples(self, tuples: Sequence[TupleWrite]) -> None:
        self.written_tuples.extend(tuples)

    def delete_tuples(self, tuples: Sequence[TupleKey]) -> None:
        self.deleted_tuples.extend(tuples)

    # Remaining methods satisfy the protocol but offer minimal behaviour.
    def check(
        self,
        subject: str,
        relation: str,
        object_: str,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> bool:
        return any(
            write.key == TupleKey(object_, relation, subject)
            for write in self.written_tuples
        )

    def lookup_resources(
        self,
        subject: str,
        relation: str,
        resource_type: str,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> Iterable[str]:
        for write in self.written_tuples:
            if write.key.subject == subject and write.key.relation == relation:
                yield write.key.object
