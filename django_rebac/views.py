"""Views for django-rebac hierarchy management.

These views provide a customer-facing UI for managing hierarchical permissions.
All views are tenant-scoped and permission-aware.

Views:
- HierarchyTreeView: Display the hierarchy tree structure
- NodeDetailView: Show node details with role assignments
- AssignRoleView: Assign a role to a user on a node
- RemoveRoleView: Remove a role from a user
- InviteUserView: Invite a new user to the hierarchy

API Views (JSON):
- APINodesView: List accessible nodes
- APINodeDetailView: Node details with roles
- APIAssignRoleView: Assign role via API
- APIRemoveRoleView: Remove role via API
- APICheckPermissionView: Check if user has permission
- APIMyNodesView: List nodes accessible to current user

Partial Views (for embedding):
- PartialHierarchyTreeView: Tree partial for HTMX/Turbo
- PartialNodeRolesView: Node roles list partial
- PartialRoleFormView: Role assignment form partial
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView

from django_rebac.conf import get_tenant_model
from django_rebac.models import HierarchyNode, HierarchyNodeRole
from django_rebac.tenant import TenantAwarePermissionEvaluator, tenant_context


User = get_user_model()


# =============================================================================
# Mixins
# =============================================================================


class TenantMixin:
    """Mixin to load and validate tenant from URL."""

    tenant = None
    tenant_ct = None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        tenant_pk = kwargs.get("tenant_pk")
        tenant_model = get_tenant_model()
        self.tenant = get_object_or_404(tenant_model, pk=tenant_pk)
        self.tenant_ct = ContentType.objects.get_for_model(tenant_model)
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_tenant_nodes(self) -> Any:
        """Get all nodes for the current tenant."""
        return HierarchyNode.objects.filter(
            tenant_content_type=self.tenant_ct,
            tenant_object_id=str(self.tenant.pk),
        )


class PermissionRequiredMixin:
    """Mixin to check permissions on nodes."""

    required_permission = "view"
    node = None

    def check_permission(self, request: HttpRequest, node: HierarchyNode) -> bool:
        """Check if user has required permission on node."""
        # Superusers and staff bypass permission checks
        if request.user.is_superuser or request.user.is_staff:
            return True
        with tenant_context(self.tenant):  # type: ignore[attr-defined]
            evaluator = TenantAwarePermissionEvaluator(
                request.user,
                tenant=self.tenant,  # type: ignore[attr-defined]
            )
            return evaluator.can(self.required_permission, node)

    def check_node_permission(
        self, request: HttpRequest, node_pk: int
    ) -> tuple[HierarchyNode | None, bool]:
        """Load node and check permission. Returns (node, has_permission)."""
        try:
            node = self.get_tenant_nodes().get(pk=node_pk)  # type: ignore[attr-defined]
        except HierarchyNode.DoesNotExist:
            return None, False

        has_perm = self.check_permission(request, node)
        return node, has_perm


class TenantPermissionMixin(LoginRequiredMixin, TenantMixin, PermissionRequiredMixin):
    """Combined mixin for tenant-scoped, permission-aware views."""

    pass


# =============================================================================
# HTML Views
# =============================================================================


class HierarchyTreeView(TenantPermissionMixin, TemplateView):
    """Display the hierarchy tree for a tenant."""

    template_name = "django_rebac/hierarchy_tree.html"
    required_permission = "view"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        # Get accessible nodes for the current user
        # Superusers and staff bypass permission filtering
        if self.request.user.is_superuser or self.request.user.is_staff:
            accessible_nodes = self.get_tenant_nodes().select_related(
                "hierarchy_type", "parent"
            )
        else:
            with tenant_context(self.tenant):
                accessible_nodes = HierarchyNode.objects.accessible_by(
                    self.request.user,
                    "view",
                ).filter(
                    tenant_content_type=self.tenant_ct,
                    tenant_object_id=str(self.tenant.pk),
                )

        # Build tree structure
        context["hierarchy_tree"] = self._build_tree(accessible_nodes)
        context["tenant"] = self.tenant
        return context

    def _build_tree(self, nodes: Any) -> list[dict[str, Any]]:
        """Build a nested tree structure from flat node list."""
        nodes_by_id = {n.pk: n for n in nodes}
        tree: list[dict[str, Any]] = []
        children_map: dict[int | None, list[dict[str, Any]]] = {}

        for node in nodes:
            node_dict = {
                "node": node,
                "children": [],
            }
            parent_id = node.parent_id
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(node_dict)

        # Get root nodes (no parent or parent not in accessible set)
        for node in nodes:
            if node.parent_id is None or node.parent_id not in nodes_by_id:
                node_dict = self._find_node_dict(children_map, node.pk)
                if node_dict:
                    self._attach_children(node_dict, children_map)
                    tree.append(node_dict)

        return tree

    def _find_node_dict(
        self, children_map: dict[int | None, list[dict[str, Any]]], node_pk: int
    ) -> dict[str, Any] | None:
        """Find node dict in children map."""
        for parent_id, children in children_map.items():
            for child in children:
                if child["node"].pk == node_pk:
                    return child
        return None

    def _attach_children(
        self, node_dict: dict[str, Any], children_map: dict[int | None, list[dict[str, Any]]]
    ) -> None:
        """Recursively attach children to node."""
        node_pk = node_dict["node"].pk
        if node_pk in children_map:
            node_dict["children"] = children_map[node_pk]
            for child in node_dict["children"]:
                self._attach_children(child, children_map)


class NodeDetailView(TenantPermissionMixin, TemplateView):
    """Display node details with role assignments."""

    template_name = "django_rebac/node_detail.html"
    required_permission = "view"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(self, "_permission_denied"):
            return self._permission_denied
        return response

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            self._permission_denied = HttpResponse(status=403)
            return self._permission_denied

        self.node = node
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["node"] = self.node
        context["roles"] = HierarchyNodeRole.objects.filter(node=self.node).select_related("user")
        context["children"] = self.node.children.all()
        context["tenant"] = self.tenant

        # Check if user can manage (for showing edit controls)
        # Superusers and staff can manage all nodes
        if self.request.user.is_superuser or self.request.user.is_staff:
            context["can_manage"] = True
        else:
            with tenant_context(self.tenant):
                evaluator = TenantAwarePermissionEvaluator(self.request.user, tenant=self.tenant)
                context["can_manage"] = evaluator.can("manage", self.node)

        # Available users for role assignment (exclude already assigned)
        assigned_user_ids = context["roles"].values_list("user_id", flat=True)
        context["available_users"] = User.objects.exclude(pk__in=assigned_user_ids)[:50]

        return context


class AssignRoleView(TenantPermissionMixin, View):
    """Assign a role to a user on a node."""

    required_permission = "manage"

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            return HttpResponse(status=403)

        user_id = request.POST.get("user_id")
        role = request.POST.get("role")

        if not user_id or not role:
            return HttpResponse("Missing user_id or role", status=400)

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return HttpResponse("User not found", status=404)

        # Create role assignment
        HierarchyNodeRole.objects.get_or_create(
            node=node,
            user=user,
            role=role,
            defaults={"created_by": request.user},
        )

        # For HTMX requests, return the updated roles partial
        if request.headers.get("HX-Request"):
            roles = list(HierarchyNodeRole.objects.filter(node=node).select_related("user"))
            if request.user.is_superuser or request.user.is_staff:
                can_manage = True
            else:
                with tenant_context(self.tenant):
                    evaluator = TenantAwarePermissionEvaluator(request.user, tenant=self.tenant)
                    can_manage = evaluator.can("manage", node)
            return render(request, "django_rebac/partials/_node_roles.html", {
                "node": node,
                "roles": roles,
                "can_manage": can_manage,
                "tenant": self.tenant,
            })

        # Regular request: redirect back to node detail
        return redirect("rebac:node_detail", tenant_pk=self.tenant.pk, node_pk=node.pk)


class RemoveRoleView(TenantPermissionMixin, View):
    """Remove a role from a user."""

    required_permission = "manage"

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        node_pk = kwargs.get("node_pk")
        role_pk = kwargs.get("role_pk")

        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            return HttpResponse(status=403)

        try:
            role = HierarchyNodeRole.objects.get(pk=role_pk, node=node)
            role.delete()
        except HierarchyNodeRole.DoesNotExist:
            return HttpResponse("Role not found", status=404)

        # For HTMX requests, return the updated roles partial
        if request.headers.get("HX-Request"):
            roles = list(HierarchyNodeRole.objects.filter(node=node).select_related("user"))
            if request.user.is_superuser or request.user.is_staff:
                can_manage = True
            else:
                with tenant_context(self.tenant):
                    evaluator = TenantAwarePermissionEvaluator(request.user, tenant=self.tenant)
                    can_manage = evaluator.can("manage", node)
            return render(request, "django_rebac/partials/_node_roles.html", {
                "node": node,
                "roles": roles,
                "can_manage": can_manage,
                "tenant": self.tenant,
            })

        return redirect("rebac:node_detail", tenant_pk=self.tenant.pk, node_pk=node.pk)


class InviteUserView(TenantPermissionMixin, View):
    """Invite a new user to the hierarchy."""

    required_permission = "manage"
    template_name = "django_rebac/invite_user.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            return HttpResponse(status=403)

        return render(request, self.template_name, {
            "node": node,
            "tenant": self.tenant,
            "roles": HierarchyNodeRole.ROLE_CHOICES,
        })

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            return HttpResponse(status=403)

        email = request.POST.get("email")
        role = request.POST.get("role")

        if not email or not role:
            return HttpResponse("Missing email or role", status=400)

        # Get or create user by email
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email.split("@")[0] + "-" + str(hash(email))[-6:],
            },
        )

        # Create role assignment
        HierarchyNodeRole.objects.get_or_create(
            node=node,
            user=user,
            role=role,
            defaults={"created_by": request.user},
        )

        return redirect("rebac:node_detail", tenant_pk=self.tenant.pk, node_pk=node.pk)


# =============================================================================
# JSON API Views
# =============================================================================


class APINodesView(TenantPermissionMixin, View):
    """API: List accessible hierarchy nodes."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        with tenant_context(self.tenant):
            accessible_nodes = HierarchyNode.objects.accessible_by(
                request.user,
                "view",
            ).filter(
                tenant_content_type=self.tenant_ct,
                tenant_object_id=str(self.tenant.pk),
            )

        nodes_data = [
            {
                "id": node.pk,
                "name": node.name,
                "slug": node.slug,
                "type": node.hierarchy_type.name,
                "type_display": node.hierarchy_type.display_name,
                "parent_id": node.parent_id,
                "depth": node.depth,
                "path": node.path,
            }
            for node in accessible_nodes
        ]

        return JsonResponse({"nodes": nodes_data}, content_type="application/json")


class APINodeDetailView(TenantPermissionMixin, View):
    """API: Get node details with roles."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            return JsonResponse({"error": "Not found or access denied"}, status=403)

        roles = HierarchyNodeRole.objects.filter(node=node).select_related("user")
        children = node.children.all()

        return JsonResponse({
            "id": node.pk,
            "name": node.name,
            "slug": node.slug,
            "type": node.hierarchy_type.name,
            "type_display": node.hierarchy_type.display_name,
            "parent_id": node.parent_id,
            "depth": node.depth,
            "path": node.path,
            "roles": [
                {
                    "id": r.pk,
                    "user_id": r.user_id,
                    "username": r.user.username,
                    "email": r.user.email,
                    "role": r.role,
                    "inheritable": r.inheritable,
                }
                for r in roles
            ],
            "children": [
                {"id": c.pk, "name": c.name, "slug": c.slug}
                for c in children
            ],
        }, content_type="application/json")


class APIAssignRoleView(TenantPermissionMixin, View):
    """API: Assign role to user."""

    required_permission = "manage"

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            return JsonResponse({"error": "Access denied"}, status=403)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        user_id = data.get("user_id")
        role = data.get("role")

        if not user_id or not role:
            return JsonResponse({"error": "Missing user_id or role"}, status=400)

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found"}, status=404)

        role_obj, created = HierarchyNodeRole.objects.get_or_create(
            node=node,
            user=user,
            role=role,
            defaults={"created_by": request.user},
        )

        return JsonResponse({
            "success": True,
            "created": created,
            "role_id": role_obj.pk,
        }, status=201 if created else 200)


class APIRemoveRoleView(TenantPermissionMixin, View):
    """API: Remove role from user."""

    required_permission = "manage"

    def delete(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        node_pk = kwargs.get("node_pk")
        role_pk = kwargs.get("role_pk")

        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            return JsonResponse({"error": "Access denied"}, status=403)

        try:
            role = HierarchyNodeRole.objects.get(pk=role_pk, node=node)
            role.delete()
        except HierarchyNodeRole.DoesNotExist:
            return JsonResponse({"error": "Role not found"}, status=404)

        return JsonResponse({"success": True}, status=200)


class APICheckPermissionView(TenantPermissionMixin, View):
    """API: Check if user has permission on node."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        user_id = data.get("user_id")
        permission = data.get("permission")
        node_id = data.get("node_id")

        if not all([user_id, permission, node_id]):
            return JsonResponse(
                {"error": "Missing user_id, permission, or node_id"},
                status=400,
            )

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found"}, status=404)

        try:
            node = self.get_tenant_nodes().get(pk=node_id)
        except HierarchyNode.DoesNotExist:
            return JsonResponse({"error": "Node not found"}, status=404)

        with tenant_context(self.tenant):
            evaluator = TenantAwarePermissionEvaluator(user, tenant=self.tenant)
            allowed = evaluator.can(permission, node)

        return JsonResponse({
            "user_id": user_id,
            "permission": permission,
            "node_id": node_id,
            "allowed": allowed,
        })


class APIMyNodesView(TenantPermissionMixin, View):
    """API: List nodes accessible to current user."""

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        permission = request.GET.get("permission", "view")

        with tenant_context(self.tenant):
            accessible_nodes = HierarchyNode.objects.accessible_by(
                request.user,
                permission,
            ).filter(
                tenant_content_type=self.tenant_ct,
                tenant_object_id=str(self.tenant.pk),
            )

        nodes_data = [
            {
                "id": node.pk,
                "name": node.name,
                "slug": node.slug,
                "type": node.hierarchy_type.name,
                "type_display": node.hierarchy_type.display_name,
                "parent_id": node.parent_id,
                "depth": node.depth,
            }
            for node in accessible_nodes
        ]

        return JsonResponse({"nodes": nodes_data, "permission": permission})


# =============================================================================
# Template Partial Views
# =============================================================================


class PartialHierarchyTreeView(TenantPermissionMixin, View):
    """Render hierarchy tree partial for embedding."""

    template_name = "django_rebac/partials/_hierarchy_tree.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        with tenant_context(self.tenant):
            accessible_nodes = HierarchyNode.objects.accessible_by(
                request.user,
                "view",
            ).filter(
                tenant_content_type=self.tenant_ct,
                tenant_object_id=str(self.tenant.pk),
            )

        context = {
            "nodes": list(accessible_nodes.order_by("path")),
            "tenant": self.tenant,
        }
        return render(request, self.template_name, context)


class PartialNodeRolesView(TenantPermissionMixin, View):
    """Render node roles list partial."""

    template_name = "django_rebac/partials/_node_roles.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if not node or not has_perm:
            context = {"roles": [], "node": None, "can_manage": False, "tenant": self.tenant}
        else:
            roles = list(HierarchyNodeRole.objects.filter(node=node).select_related("user"))
            # Superusers and staff can manage all nodes
            if request.user.is_superuser or request.user.is_staff:
                can_manage = True
            else:
                with tenant_context(self.tenant):
                    evaluator = TenantAwarePermissionEvaluator(request.user, tenant=self.tenant)
                    can_manage = evaluator.can("manage", node)

            context = {
                "node": node,
                "roles": roles,
                "can_manage": can_manage,
                "tenant": self.tenant,
            }
        return render(request, self.template_name, context)


class PartialRoleFormView(TenantPermissionMixin, View):
    """Render role assignment form partial."""

    template_name = "django_rebac/partials/_role_form.html"
    required_permission = "manage"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        node_pk = kwargs.get("node_pk")
        node, has_perm = self.check_node_permission(request, node_pk)

        if node and has_perm:
            context = {
                "node": node,
                "roles": HierarchyNodeRole.ROLE_CHOICES,
                "users": list(User.objects.all()[:50]),
                "tenant": self.tenant,
            }
        else:
            context = {"node": None, "roles": [], "users": []}

        return render(request, self.template_name, context)
