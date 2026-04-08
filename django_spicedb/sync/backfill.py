"""Backfill helpers for emitting tuples to the adapter."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from django.utils.module_loading import import_string

from django_spicedb.adapters.base import RebacAdapter, TupleKey, TupleWrite
from django_spicedb.runtime.last_write_token import record_write_token


def backfill_tuples(
    adapter: RebacAdapter,
    tuples: Iterable[TupleWrite],
    *,
    batch_size: int = 100,
) -> int:
    """Write tuples to the adapter in batches, returning the count written."""

    buffer: list[TupleWrite] = []
    total = 0
    last_token = ""
    for tuple_write in tuples:
        buffer.append(tuple_write)
        if len(buffer) >= batch_size:
            last_token = adapter.write_tuples(buffer) or last_token
            total += len(buffer)
            buffer = []

    if buffer:
        last_token = adapter.write_tuples(buffer) or last_token
        total += len(buffer)

    record_write_token(last_token)
    return total


def generate_through_tuples(
    type_name: str,
    cfg: Mapping[str, Any],
) -> Iterable[TupleWrite]:
    """Generate TupleWrite objects for all through-table bindings on a type.

    Queries the through model, filters by role_value, and yields tuples.
    """
    bindings = cfg.get("bindings", {})
    relations = cfg.get("relations", {})

    for relation_name, binding_config in bindings.items():
        if binding_config.get("kind") != "through":
            continue

        through_model_path = binding_config.get("model", "")
        if not through_model_path:
            continue

        object_fk = binding_config.get("object_fk", "")
        subject_fk = binding_config.get("subject_fk", "")
        role_field = binding_config.get("role_field", "")
        role_value = binding_config.get("role_value", "")

        relation_target = relations.get(relation_name, "")
        if not relation_target:
            continue

        # Parse subject type
        if "#" in relation_target:
            subject_type, subject_relation = relation_target.split("#", 1)
        else:
            subject_type = relation_target
            subject_relation = None

        through_model = import_string(through_model_path)
        object_fk_id = f"{object_fk}_id"
        subject_fk_id = f"{subject_fk}_id"

        # Query rows matching this role value
        filters = {}
        if role_field and role_value:
            filters[role_field] = role_value

        for row in through_model.objects.filter(**filters).iterator():
            obj_id = getattr(row, object_fk_id, None)
            subj_id = getattr(row, subject_fk_id, None)
            if obj_id is None or subj_id is None:
                continue

            subject_ref = f"{subject_type}:{subj_id}"
            if subject_relation:
                subject_ref = f"{subject_ref}#{subject_relation}"

            yield TupleWrite(
                key=TupleKey(
                    object=f"{type_name}:{obj_id}",
                    relation=relation_name,
                    subject=subject_ref,
                )
            )
