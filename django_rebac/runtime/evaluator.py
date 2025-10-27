"""Permission evaluation utilities."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model

import django_rebac.conf as conf
from django_rebac.adapters import factory
from django_rebac.adapters.base import RebacAdapter


class PermissionEvaluator:
    """Request-scoped helper that batches and caches permission checks."""

    def __init__(
        self,
        subject: Any,
        *,
        adapter: RebacAdapter | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self._adapter = adapter or factory.get_adapter()
        self._default_context = dict(context or {})
        self._subject_ref = _subject_to_reference(subject)
        self._cache: MutableMapping[tuple, bool] = {}

    def can(
        self,
        relation: str,
        obj: Model,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> bool:
        object_ref = _object_to_reference(obj)
        cache_key = (
            relation,
            object_ref,
            _freeze_context(context, self._default_context),
            consistency,
        )
        if cache_key not in self._cache:
            ctx = _merge_context(context, self._default_context)
            result = self._adapter.check(
                subject=self._subject_ref,
                relation=relation,
                object_=object_ref,
                context=ctx,
                consistency=consistency,
            )
            self._cache[cache_key] = result
        return self._cache[cache_key]

    def batch_can(
        self,
        relation: str,
        objects: Iterable[Model],
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> dict[Model, bool]:
        return {
            obj: self.can(relation, obj, context=context, consistency=consistency)
            for obj in objects
        }

    def lookup_resources(
        self,
        relation: str,
        model: type[Model],
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> Sequence[Any]:
        resource_type = conf.get_type_for_model(model)
        ctx = _merge_context(context, self._default_context)
        ids = self._adapter.lookup_resources(
            subject=self._subject_ref,
            relation=relation,
            resource_type=resource_type,
            context=ctx,
            consistency=consistency,
        )
        return list(ids)


def can(
    subject: Any,
    relation: str,
    obj: Model,
    *,
    adapter: RebacAdapter | None = None,
    context: Mapping[str, Any] | None = None,
    consistency: str | None = None,
) -> bool:
    """Convenience wrapper around :class:`PermissionEvaluator`."""

    evaluator = PermissionEvaluator(subject, adapter=adapter, context=context)
    return evaluator.can(relation, obj, consistency=consistency)


# ---------------------------------------------------------------------------
# Helpers


def _subject_to_reference(subject: Any) -> str:
    if isinstance(subject, str):
        return subject
    if isinstance(subject, Model):
        subject_type = conf.get_type_for_model(subject.__class__)
        if subject.pk is None:
            raise ImproperlyConfigured("Subject instance must be saved before permission checks.")
        return f"{subject_type}:{subject.pk}"
    raise ImproperlyConfigured(
        "Subject must be either a Django model instance or a SpiceDB reference string."
    )


def _object_to_reference(obj: Model) -> str:
    if obj.pk is None:
        raise ImproperlyConfigured("Target object must be saved before permission checks.")
    object_type = conf.get_type_for_model(obj.__class__)
    return f"{object_type}:{obj.pk}"


def _merge_context(
    override: Mapping[str, Any] | None,
    default: Mapping[str, Any],
) -> Mapping[str, Any]:
    if not override:
        return default
    merged = dict(default)
    merged.update(override)
    return merged


def _freeze_context(
    override: Mapping[str, Any] | None,
    default: Mapping[str, Any],
) -> tuple:
    merged = _merge_context(override, default)
    if not merged:
        return tuple()
    return tuple(sorted(merged.items()))
