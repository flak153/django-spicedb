"""URL configuration for django-rebac hierarchy management views.

Include these URLs in your project's urlpatterns:

    from django.urls import path, include

    urlpatterns = [
        path("rebac/", include("django_rebac.urls")),
    ]

All views are tenant-scoped and permission-aware.
"""

from django.urls import path

from django_rebac import views

app_name = "rebac"

urlpatterns = [
    # HTML Views
    path(
        "<int:tenant_pk>/hierarchy/",
        views.HierarchyTreeView.as_view(),
        name="hierarchy_tree",
    ),
    path(
        "<int:tenant_pk>/node/<int:node_pk>/",
        views.NodeDetailView.as_view(),
        name="node_detail",
    ),
    path(
        "<int:tenant_pk>/node/<int:node_pk>/assign/",
        views.AssignRoleView.as_view(),
        name="assign_role",
    ),
    path(
        "<int:tenant_pk>/node/<int:node_pk>/role/<int:role_pk>/remove/",
        views.RemoveRoleView.as_view(),
        name="remove_role",
    ),
    path(
        "<int:tenant_pk>/node/<int:node_pk>/invite/",
        views.InviteUserView.as_view(),
        name="invite_user",
    ),
    # JSON API Endpoints
    path(
        "<int:tenant_pk>/api/nodes/",
        views.APINodesView.as_view(),
        name="api_nodes",
    ),
    path(
        "<int:tenant_pk>/api/node/<int:node_pk>/",
        views.APINodeDetailView.as_view(),
        name="api_node_detail",
    ),
    path(
        "<int:tenant_pk>/api/node/<int:node_pk>/assign/",
        views.APIAssignRoleView.as_view(),
        name="api_assign_role",
    ),
    path(
        "<int:tenant_pk>/api/node/<int:node_pk>/role/<int:role_pk>/",
        views.APIRemoveRoleView.as_view(),
        name="api_remove_role",
    ),
    path(
        "<int:tenant_pk>/api/check/",
        views.APICheckPermissionView.as_view(),
        name="api_check_permission",
    ),
    path(
        "<int:tenant_pk>/api/my-nodes/",
        views.APIMyNodesView.as_view(),
        name="api_my_nodes",
    ),
    # Template Partials (for HTMX/Turbo or embedding)
    path(
        "<int:tenant_pk>/partial/tree/",
        views.PartialHierarchyTreeView.as_view(),
        name="partial_hierarchy_tree",
    ),
    path(
        "<int:tenant_pk>/partial/node/<int:node_pk>/roles/",
        views.PartialNodeRolesView.as_view(),
        name="partial_node_roles",
    ),
    path(
        "<int:tenant_pk>/partial/node/<int:node_pk>/role-form/",
        views.PartialRoleFormView.as_view(),
        name="partial_role_form",
    ),
]
