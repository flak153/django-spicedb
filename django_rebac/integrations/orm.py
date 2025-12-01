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


# =============================================================================
# Tenant-Aware QuerySet for Hierarchy Models
# =============================================================================


class TenantAwareRebacQuerySet(RebacQuerySet):
    """
    QuerySet that automatically filters by current tenant context.

    Use this for models that have tenant_content_type and tenant_object_id fields.
    """

    def accessible_by(
        self,
        subject: Any,
        relation: str,
        *,
        evaluator: PermissionEvaluator | None = None,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ):
        from django_rebac.tenant import get_current_tenant

        # Get current tenant and filter first
        tenant = get_current_tenant()
        qs = self

        if tenant is not None:
            from django.contrib.contenttypes.models import ContentType

            tenant_ct = ContentType.objects.get_for_model(tenant)
            qs = qs.filter(
                tenant_content_type=tenant_ct,
                tenant_object_id=str(tenant.pk),
            )

        # Then apply permission filter
        evaluator = evaluator or PermissionEvaluator(subject)
        resource_ids = evaluator.lookup_resources(
            relation=relation,
            model=self.model,
            context=context,
            consistency=consistency,
        )

        if not resource_ids:
            return qs.none()

        pk_field = self.model._meta.pk
        parsed_ids = [pk_field.to_python(value) for value in resource_ids]
        return qs.filter(pk__in=parsed_ids)


class TenantAwareRebacManager(models.Manager.from_queryset(TenantAwareRebacQuerySet)):  # type: ignore[misc]
    pass
