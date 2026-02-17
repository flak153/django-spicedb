"""Base adapter definitions for django-spicedb."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class TupleKey:
    object: str
    relation: str
    subject: str


@dataclass(frozen=True)
class TupleWrite:
    key: TupleKey
    condition: Mapping[str, Any] | None = None


class RebacAdapter(Protocol):
    """Protocol describing the contract for SpiceDB adapters."""

    def publish_schema(self, schema: str) -> str:
        """Apply the given schema and return an adapter-specific token."""

    def write_tuples(self, tuples: Sequence[TupleWrite]) -> None:
        """Persist tuple writes."""

    def delete_tuples(self, tuples: Sequence[TupleKey]) -> None:
        """Delete tuples by key."""

    def check(
        self,
        subject: str,
        relation: str,
        object_: str,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> bool:
        ...

    def batch_check(
        self,
        subject: str,
        relation: str,
        objects: Sequence[str],
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> list[bool]:
        """Check permissions for multiple objects in a single call.

        Default implementation falls back to sequential checks.
        """
        return [
            self.check(subject, relation, obj, context=context, consistency=consistency)
            for obj in objects
        ]

    def lookup_resources(
        self,
        subject: str,
        relation: str,
        resource_type: str,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
        max_results: int | None = None,
    ) -> Iterable[str]:
        ...
