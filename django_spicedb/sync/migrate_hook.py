"""Post-migrate hook that publishes schema and backfills tuples."""

from __future__ import annotations

import logging
from typing import Any

from django.utils.module_loading import import_string

from django_spicedb.adapters.factory import get_adapter
from django_spicedb.conf import get_type_graph
from django_spicedb.schema import publish_schema
from django_spicedb.sync.backfill import backfill_tuples, generate_through_tuples
from django_spicedb.sync.registry import _gather_tuple_writes

logger = logging.getLogger(__name__)

# Module-level guard: ensures we run only once per migrate invocation,
# even though post_migrate fires once per installed app.
_has_run = False


def reset_migrate_hook() -> None:
    """Reset the once-per-migrate guard. Primarily for tests."""
    global _has_run
    _has_run = False


def handle_post_migrate(sender: Any, **kwargs: Any) -> None:
    """Publish schema + backfill tuples after migrate completes.

    Runs only once per process (guarded by ``_has_run``).  Skips
    gracefully if SpiceDB is unreachable so ``migrate`` never crashes.
    """
    global _has_run
    if _has_run:
        return
    _has_run = True

    verbosity = kwargs.get("verbosity", 1)

    # --- publish schema ---------------------------------------------------
    try:
        graph = get_type_graph()
        adapter = get_adapter()
        digest = publish_schema(adapter, graph=graph)
        if verbosity >= 1:
            logger.info(
                "post_migrate: published schema for %d type(s) (digest: %s)",
                len(graph.types),
                digest[:12],
            )
    except Exception:
        logger.warning(
            "post_migrate: could not publish schema to SpiceDB — "
            "is SpiceDB running? Skipping schema publish and backfill.",
            exc_info=True,
        )
        return  # no point backfilling if schema publish failed

    # --- backfill tuples --------------------------------------------------
    try:
        total = 0
        for type_name, cfg in graph.types.items():
            if not cfg.model or not cfg.bindings:
                continue

            model = import_string(cfg.model)
            flat: list = []
            for inst in model.objects.iterator():
                flat.extend(_gather_tuple_writes(type_name, cfg, inst))

            cfg_dict = {"bindings": cfg.bindings, "relations": cfg.relations}
            flat.extend(generate_through_tuples(type_name, cfg_dict))

            if flat:
                total += backfill_tuples(adapter, flat)

        if verbosity >= 1:
            logger.info("post_migrate: backfilled %d tuple(s)", total)
    except Exception:
        logger.warning(
            "post_migrate: tuple backfill failed — "
            "is SpiceDB running? Skipping.",
            exc_info=True,
        )
