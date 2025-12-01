"""
Multi-tenant context management and permission evaluation.

This module provides:
- Thread-local tenant context management
- Tenant-aware permission evaluation with cross-tenant isolation
- Efficient hierarchy node lookups with caching
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Mapping, Set

from django.db.models import Model

from django_rebac.adapters import factory
from django_rebac.runtime.evaluator import PermissionEvaluator


# =============================================================================
# Thread-Local Tenant Context
# =============================================================================

_tenant_context = threading.local()


def get_current_tenant() -> Any | None:
    """
    Get the current tenant from thread-local storage.

    Returns:
        The current tenant instance, or None if not set.
    """
    return getattr(_tenant_context, "tenant", None)


def set_current_tenant(tenant: Any) -> None:
    """
    Set the current tenant in thread-local storage.

    Args:
        tenant: The tenant instance to set as current.
    """
    _tenant_context.tenant = tenant


def clear_current_tenant() -> None:
    """Clear the current tenant from thread-local storage."""
    _tenant_context.tenant = None


@contextmanager
def tenant_context(tenant: Any):
    """
    Context manager for scoped tenant context.

    Sets the tenant for the duration of the context, then restores
    the previous tenant (or None) on exit.

    Example:
        with tenant_context(company):
            # All operations here see company as the tenant
            nodes = HierarchyNode.objects.accessible_by(user, "view")
    """
    previous = get_current_tenant()
    set_current_tenant(tenant)
    try:
        yield tenant
    finally:
        if previous is None:
            clear_current_tenant()
        else:
            set_current_tenant(previous)


# =============================================================================
# Tenant-Aware Permission Evaluator
# =============================================================================


class TenantAwarePermissionEvaluator(PermissionEvaluator):
    """
    Permission evaluator with automatic cross-tenant isolation.

    Before calling SpiceDB, this evaluator checks that the target object
    belongs to the same tenant as the evaluator's context. Cross-tenant
    access is automatically denied without hitting SpiceDB.

    Example:
        evaluator = TenantAwarePermissionEvaluator(user, tenant=company)

        # Same tenant - defers to SpiceDB
        evaluator.can("view", node_in_company)  # True/False from SpiceDB

        # Cross-tenant - automatic denial
        evaluator.can("view", node_in_other_company)  # Always False
    """

    def __init__(
        self,
        subject: Any,
        *,
        tenant: Any,
        adapter=None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(subject, adapter=adapter, context=context)
        self._tenant = tenant

    def can(
        self,
        relation: str,
        obj: Model,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> bool:
        """
        Check permission with tenant isolation.

        Cross-tenant access is automatically denied without calling SpiceDB.
        """
        # Check tenant isolation first
        if not self._is_same_tenant(obj):
            return False

        # Same tenant - defer to SpiceDB
        return super().can(relation, obj, context=context, consistency=consistency)

    def _is_same_tenant(self, obj: Model) -> bool:
        """Check if the object belongs to the same tenant."""
        # Get tenant info from the object
        obj_tenant_id = getattr(obj, "tenant_object_id", None)

        if obj_tenant_id is None:
            # Object doesn't have tenant_object_id - check for direct FK
            obj_tenant = getattr(obj, "tenant", None)
            if obj_tenant is not None:
                return obj_tenant.pk == self._tenant.pk
            # No tenant info on object - allow (non-tenant-scoped model)
            return True

        # Compare tenant IDs
        return str(obj_tenant_id) == str(self._tenant.pk)

    def filter_accessible(
        self,
        queryset,
        relation: str,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ):
        """
        Filter a queryset to only objects the subject can access.

        Automatically filters by tenant first, then by permission.
        """
        # First filter by tenant
        from django.contrib.contenttypes.models import ContentType

        tenant_ct = ContentType.objects.get_for_model(self._tenant)
        qs = queryset.filter(
            tenant_content_type=tenant_ct,
            tenant_object_id=str(self._tenant.pk),
        )

        # Then filter by permission
        resource_ids = self.lookup_resources(
            relation=relation,
            model=queryset.model,
            context=context,
            consistency=consistency,
        )

        if not resource_ids:
            return qs.none()

        return qs.filter(pk__in=resource_ids)


# =============================================================================
# Tenant Hierarchy Lookup Helper
# =============================================================================


class TenantHierarchyLookup:
    """
    Efficient lookup helper for hierarchy node permissions.

    Caches the set of accessible node IDs to avoid repeated LookupResources
    calls within a single request.

    Example:
        lookup = TenantHierarchyLookup(user, company)

        # Get all viewable hierarchy nodes (one SpiceDB call)
        viewable_ids = lookup.get_accessible_hierarchy_nodes("view")

        # Use for filtering related models
        employees = Employee.objects.filter(hierarchy_node_id__in=viewable_ids)
    """

    def __init__(self, user: Any, tenant: Any) -> None:
        self._user = user
        self._tenant = tenant
        self._cache: dict[str, Set[int]] = {}

        # Get adapter for lookups
        self._adapter = factory.get_adapter()

        # Build subject reference
        if hasattr(user, "pk"):
            from django_rebac.conf import get_type_for_model
            try:
                user_type = get_type_for_model(user.__class__)
                self._subject_ref = f"{user_type}:{user.pk}"
            except Exception:
                self._subject_ref = f"user:{user.pk}"
        else:
            self._subject_ref = str(user)

    def get_accessible_hierarchy_nodes(self, permission: str = "view") -> Set[int]:
        """
        Get the set of hierarchy node IDs the user can access.

        Results are cached per permission type.

        Args:
            permission: The permission to check (e.g., "view", "manage")

        Returns:
            Set of hierarchy node primary keys the user can access.
        """
        if permission in self._cache:
            return self._cache[permission]

        # Call LookupResources for hierarchy_node type
        ids = self._adapter.lookup_resources(
            subject=self._subject_ref,
            relation=permission,
            resource_type="hierarchy_node",
        )

        # Convert to set of integers and cache
        accessible_ids = {int(id_) for id_ in ids}
        self._cache[permission] = accessible_ids

        return accessible_ids

    def filter_queryset(self, queryset, permission: str = "view"):
        """
        Filter a queryset by accessible hierarchy nodes.

        For models with a hierarchy_node FK, this is more efficient than
        per-object permission checks.

        Args:
            queryset: QuerySet with hierarchy_node FK
            permission: Permission to check

        Returns:
            Filtered queryset
        """
        accessible_ids = self.get_accessible_hierarchy_nodes(permission)
        return queryset.filter(hierarchy_node_id__in=accessible_ids)

    def clear_cache(self) -> None:
        """Clear the cached results."""
        self._cache.clear()
