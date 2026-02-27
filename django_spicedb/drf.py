"""Django REST Framework integration for django-spicedb."""

try:
    from rest_framework.permissions import BasePermission
    from rest_framework.filters import BaseFilterBackend
except ImportError:
    raise ImportError(
        "djangorestframework is required for DRF integration. "
        "Install it with: pip install django-spicedb[drf] "
        "(or: pip install djangorestframework)."
    )

from django_spicedb.runtime.evaluator import PermissionEvaluator


class ReBACPermission(BasePermission):
    """
    DRF permission class that checks SpiceDB permissions per object.

    Usage::

        class DocumentViewSet(ModelViewSet):
            permission_classes = [ReBACPermission]
            rebac_permission = "view"
            # or per-action:
            rebac_action_permissions = {
                "list": "view", "retrieve": "view",
                "update": "edit", "destroy": "delete",
            }
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        permission = self._get_permission(request, view)
        if not permission:
            return True
        evaluator = PermissionEvaluator(request.user)
        return evaluator.can(permission, obj)

    def _get_permission(self, request, view):
        action_map = getattr(view, "rebac_action_permissions", {})
        action = getattr(view, "action", None)
        if action and action in action_map:
            return action_map[action]
        return getattr(view, "rebac_permission", None)


class ReBACFilterBackend(BaseFilterBackend):
    """
    DRF filter backend that auto-filters querysets by SpiceDB permissions.

    Usage::

        class DocumentViewSet(ModelViewSet):
            filter_backends = [ReBACFilterBackend]
            rebac_filter_permission = "view"  # defaults to "view"
    """

    def filter_queryset(self, request, queryset, view):
        permission = getattr(view, "rebac_filter_permission", "view")
        if hasattr(queryset, "accessible_by"):
            return queryset.accessible_by(request.user, permission)
        return queryset
