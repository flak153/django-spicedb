"""ORM integration helpers."""

from __future__ import annotations

from typing import Any, Mapping

from django.db import models

import django_rebac.conf as conf
from django_rebac.runtime.evaluator import PermissionEvaluator


class RebacQuerySet(models.QuerySet):
    def accessible_by(
        self,
        subject: Any,
        relation: str,
        *,
        evaluator: PermissionEvaluator | None = None,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ):
        evaluator = evaluator or PermissionEvaluator(subject)
        resource_ids = evaluator.lookup_resources(
            relation=relation,
            model=self.model,
            context=context,
            consistency=consistency,
        )
        if not resource_ids:
            return self.none()
        pk_field = self.model._meta.pk
        parsed_ids = [pk_field.to_python(value) for value in resource_ids]
        return self.filter(pk__in=parsed_ids)


class RebacManager(models.Manager.from_queryset(RebacQuerySet)):  # type: ignore[misc]
    pass
