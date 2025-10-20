"""Backfill helpers for emitting tuples to the adapter."""

from __future__ import annotations

from typing import Iterable, Sequence

from django_rebac.adapters.base import RebacAdapter, TupleWrite


def backfill_tuples(
    adapter: RebacAdapter,
    tuples: Iterable[TupleWrite],
    *,
    batch_size: int = 100,
) -> int:
    """Write tuples to the adapter in batches, returning the count written."""

    buffer: list[TupleWrite] = []
    total = 0
    for tuple_write in tuples:
        buffer.append(tuple_write)
        if len(buffer) >= batch_size:
            adapter.write_tuples(buffer)
            total += len(buffer)
            buffer = []

    if buffer:
        adapter.write_tuples(buffer)
        total += len(buffer)

    return total
