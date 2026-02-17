"""Tuple reconciliation module for detecting and fixing sync drift."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.utils.module_loading import import_string

from django_spicedb.adapters import factory
from django_spicedb.adapters.base import RebacAdapter, TupleWrite
from django_spicedb.conf import get_type_graph
from django_spicedb.sync.backfill import generate_through_tuples
from django_spicedb.sync.registry import _gather_tuple_writes

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    """Result of reconciling tuples for a single type."""

    type_name: str
    expected: int     # tuples that should exist based on Django state
    to_write: int     # tuples that would be written to SpiceDB on fix
    stale: int        # tuples in SpiceDB but not in Django (would be deleted on fix)
    fixed: bool       # whether fixes were applied


def reconcile_type(
    type_name: str,
    *,
    fix: bool = False,
    adapter: RebacAdapter | None = None,
) -> ReconcileResult:
    """Reconcile tuples for a single type.

    Computes expected tuples from Django state and optionally writes missing tuples.

    NOTE: Detecting "stale" tuples (in SpiceDB but not in Django) requires a
    read_tuples() method on the adapter, which is not currently part of the
    RebacAdapter protocol. Therefore, the `stale` field will always be 0 in the
    current implementation.

    Args:
        type_name: Name of the ReBAC type to reconcile
        fix: If True, write missing tuples to SpiceDB
        adapter: Optional adapter instance (defaults to factory.get_adapter())

    Returns:
        ReconcileResult with counts of expected, missing, and stale tuples
    """
    if adapter is None:
        adapter = factory.get_adapter()

    graph = get_type_graph()
    cfg = graph.types.get(type_name)

    if cfg is None:
        logger.warning(f"Type {type_name!r} not found in type graph")
        return ReconcileResult(
            type_name=type_name,
            expected=0,
            to_write=0,
            stale=0,
            fixed=False,
        )

    if not cfg.model:
        logger.warning(f"Type {type_name!r} has no model configured")
        return ReconcileResult(
            type_name=type_name,
            expected=0,
            to_write=0,
            stale=0,
            fixed=False,
        )

    # Load the Django model
    model = import_string(cfg.model)

    # Gather expected tuples from Django state
    expected_tuples: list[TupleWrite] = []

    # Collect tuples from FK/M2M bindings
    if cfg.bindings:
        for instance in model.objects.iterator():
            expected_tuples.extend(_gather_tuple_writes(type_name, cfg, instance))

    # Collect tuples from through-table bindings
    # Note: generate_through_tuples expects a dict-like config
    cfg_dict = {
        "bindings": cfg.bindings,
        "relations": cfg.relations,
    }
    expected_tuples.extend(generate_through_tuples(type_name, cfg_dict))

    expected_count = len(expected_tuples)

    # Until a read_tuples() API exists we re-write all expected tuples on fix.
    to_write_count = expected_count
    stale_count = 0  # Can't detect without a read_tuples() adapter method

    if fix and expected_tuples:
        logger.info(f"Writing {to_write_count} tuples for type {type_name!r}")
        adapter.write_tuples(expected_tuples)
        fixed = True
    else:
        fixed = False

    return ReconcileResult(
        type_name=type_name,
        expected=expected_count,
        to_write=to_write_count,
        stale=stale_count,
        fixed=fixed,
    )


def reconcile_all(
    *,
    fix: bool = False,
    types: list[str] | None = None,
    adapter: RebacAdapter | None = None,
) -> list[ReconcileResult]:
    """Reconcile tuples for all types (or a filtered list).

    Args:
        fix: If True, write missing tuples to SpiceDB
        types: Optional list of type names to reconcile (defaults to all types)
        adapter: Optional adapter instance (defaults to factory.get_adapter())

    Returns:
        List of ReconcileResult objects
    """
    if adapter is None:
        adapter = factory.get_adapter()

    graph = get_type_graph()

    # Determine which types to reconcile
    type_names = types if types is not None else list(graph.types.keys())

    results = []
    for type_name in type_names:
        result = reconcile_type(type_name, fix=fix, adapter=adapter)
        results.append(result)

    return results


def reconcile_tuples(
    *,
    fix: bool = False,
    types: list[str] | None = None,
    dry_run: bool = False,
) -> list[ReconcileResult]:
    """Main entry point for tuple reconciliation (Celery-friendly).

    This function can be used as a Celery task:

        from django_spicedb.sync.reconcile import reconcile_tuples

        @celery_app.task
        def reconcile_permissions():
            results = reconcile_tuples(fix=True)
            return [r.type_name for r in results if r.to_write > 0]

    Args:
        fix: If True, write missing tuples to SpiceDB
        types: Optional list of type names to reconcile (defaults to all types)
        dry_run: If True, just report what would be done (same as fix=False
            but with logging)

    Returns:
        List of ReconcileResult objects
    """
    # dry_run is essentially the same as fix=False, but we log the intent
    if dry_run:
        logger.info("Running reconciliation in dry-run mode (no changes will be made)")
        fix = False

    adapter = factory.get_adapter()
    results = reconcile_all(fix=fix, types=types, adapter=adapter)

    # Log summary
    total_expected = sum(r.expected for r in results)
    total_to_write = sum(r.to_write for r in results)
    total_stale = sum(r.stale for r in results)

    logger.info(
        f"Reconciliation complete: {len(results)} types, "
        f"{total_expected} expected tuples, "
        f"{total_to_write} to write, "
        f"{total_stale} stale"
    )

    return results
