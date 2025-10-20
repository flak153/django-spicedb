"""Schema compilation and publishing helpers."""

from __future__ import annotations

import hashlib
from typing import Tuple

import django_rebac.conf as conf

from .adapters.base import RebacAdapter
from .types import TypeGraph


def compile_schema(graph: TypeGraph) -> tuple[str, str]:
    """Return the schema string and its SHA256 hex digest."""

    schema = graph.compile_schema()
    digest = hashlib.sha256(schema.encode("utf-8")).hexdigest()
    return schema, digest


def publish_schema(adapter: RebacAdapter, *, graph: TypeGraph | None = None) -> str:
    """Compile and publish the current schema using ``adapter``."""

    active_graph = graph or conf.get_type_graph()
    schema, digest = compile_schema(active_graph)
    adapter.publish_schema(schema)
    return digest
