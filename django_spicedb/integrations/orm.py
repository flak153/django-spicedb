"""ORM integration helpers."""

from __future__ import annotations

import logging
from functools import reduce
from operator import or_
from typing import Any, Mapping

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from django_spicedb.runtime.evaluator import PermissionEvaluator

logger = logging.getLogger(__name__)


class RebacQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        """Override bulk_create to sync tuples after creation."""
        result = super().bulk_create(objs, **kwargs)
        from django_spicedb.sync.registry import sync_instances
        sync_instances(result)
        return result

    def update(self, **kwargs):
        """Override update to auto-sync FK tuple changes to SpiceDB."""
        from django_spicedb.sync.registry import _sync_queryset_update_impl
        return _sync_queryset_update_impl(self, super().update, **kwargs)

    def accessible_by(
        self,
        subject: Any,
        relation: str,
        *,
        evaluator: PermissionEvaluator | None = None,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
        max_results: int | None = None,
    ):
        evaluator = evaluator or PermissionEvaluator(subject)
        resource_ids = evaluator.lookup_resources(
            relation=relation,
            model=self.model,
            context=context,
            consistency=consistency,
            max_results=max_results,
        )
        if not resource_ids:
            return self.none()
        pk_field = self.model._meta.pk
        parsed_ids = []
        for value in resource_ids:
            try:
                parsed_ids.append(pk_field.to_python(value))
            except (ValueError, ValidationError):
                logger.warning("Skipping invalid PK value from SpiceDB: %r", value)
                continue
        if not parsed_ids:
            return self.none()
        # Chunk into batches of 500 to avoid "too many SQL variables" errors
        chunk_size = 500
        if len(parsed_ids) <= chunk_size:
            return self.filter(pk__in=parsed_ids)
        chunks = [parsed_ids[i:i + chunk_size] for i in range(0, len(parsed_ids), chunk_size)]
        q = reduce(or_, (Q(pk__in=chunk) for chunk in chunks))
        return self.filter(q)


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
        max_results: int | None = None,
    ):
        from django_spicedb.tenant import get_current_tenant

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
            max_results=max_results,
        )

        if not resource_ids:
            return qs.none()

        pk_field = self.model._meta.pk
        parsed_ids = []
        for value in resource_ids:
            try:
                parsed_ids.append(pk_field.to_python(value))
            except (ValueError, ValidationError):
                logger.warning("Skipping invalid PK value from SpiceDB: %r", value)
                continue
        if not parsed_ids:
            return qs.none()
        # Chunk into batches of 500 to avoid "too many SQL variables" errors
        chunk_size = 500
        if len(parsed_ids) <= chunk_size:
            return qs.filter(pk__in=parsed_ids)
        chunks = [parsed_ids[i:i + chunk_size] for i in range(0, len(parsed_ids), chunk_size)]
        q = reduce(or_, (Q(pk__in=chunk) for chunk in chunks))
        return qs.filter(q)


class TenantAwareRebacManager(models.Manager.from_queryset(TenantAwareRebacQuerySet)):  # type: ignore[misc]
    pass


# =============================================================================
# Through-Table QuerySet/Manager for bulk_create support
# =============================================================================


class RebacThroughQuerySet(models.QuerySet):
    """QuerySet for through-table models that syncs tuples on bulk_create."""

    def bulk_create(self, objs, **kwargs):
        """Override bulk_create to sync through-table tuples after creation."""
        result = super().bulk_create(objs, **kwargs)
        from django_spicedb.sync.registry import sync_through_instances
        sync_through_instances(result)
        return result


class RebacThroughManager(models.Manager.from_queryset(RebacThroughQuerySet)):  # type: ignore[misc]
    pass
