"""Django admin registration for django-spicedb models."""

from django.contrib import admin

from django_rebac.models import (
    AuditLog,
    Grant,
    HierarchyNode,
    HierarchyNodeRole,
    HierarchyTypeDefinition,
    Job,
    TypeDefinition,
)


# =============================================================================
# Core Models Admin
# =============================================================================


@admin.register(TypeDefinition)
class TypeDefinitionAdmin(admin.ModelAdmin):
    """Admin for TypeDefinition model."""

    list_display = ("name", "model", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "model", "description")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name",)


@admin.register(Grant)
class GrantAdmin(admin.ModelAdmin):
    """Admin for Grant model."""

    list_display = (
        "subject_type",
        "subject_id",
        "relation",
        "object_type",
        "object_id",
        "expires_at",
    )
    list_filter = ("subject_type", "object_type", "relation")
    search_fields = ("subject_id", "object_id", "notes")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    """Admin for Job model."""

    list_display = ("id", "kind", "status", "started_at", "finished_at")
    list_filter = ("kind", "status")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
    date_hierarchy = "created_at"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin for AuditLog model."""

    list_display = ("action", "actor", "created_at")
    list_filter = ("action",)
    search_fields = ("action", "actor")
    readonly_fields = ("action", "actor", "payload", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# =============================================================================
# Hierarchy Models Admin
# =============================================================================


@admin.register(HierarchyTypeDefinition)
class HierarchyTypeDefinitionAdmin(admin.ModelAdmin):
    """Admin for HierarchyTypeDefinition model."""

    list_display = (
        "name",
        "display_name",
        "level",
        "parent_type",
        "is_active",
        "tenant_content_type",
    )
    list_filter = ("tenant_content_type", "level", "is_active")
    search_fields = ("name", "display_name", "slug")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("tenant_content_type", "tenant_object_id", "level", "name")

    fieldsets = (
        (None, {
            "fields": ("name", "display_name", "slug")
        }),
        ("Hierarchy", {
            "fields": ("level", "parent_type")
        }),
        ("Tenant", {
            "fields": ("tenant_content_type", "tenant_object_id")
        }),
        ("Relations & Permissions", {
            "fields": ("relations", "permissions"),
            "classes": ("collapse",),
        }),
        ("UI Metadata", {
            "fields": ("icon", "color", "metadata_schema"),
            "classes": ("collapse",),
        }),
        ("Status", {
            "fields": ("is_active", "created_at", "updated_at")
        }),
    )


class HierarchyNodeRoleInline(admin.TabularInline):
    """Inline admin for HierarchyNodeRole on HierarchyNode."""

    model = HierarchyNodeRole
    extra = 1
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(HierarchyNode)
class HierarchyNodeAdmin(admin.ModelAdmin):
    """Admin for HierarchyNode model."""

    list_display = (
        "name",
        "hierarchy_type",
        "parent",
        "depth",
        "is_active",
    )
    list_filter = (
        "tenant_content_type",
        "hierarchy_type",
        "depth",
        "is_active",
    )
    search_fields = ("name", "slug", "code")
    readonly_fields = ("path", "depth", "created_at", "updated_at")
    ordering = ("tenant_content_type", "tenant_object_id", "path")
    autocomplete_fields = ("parent",)

    inlines = [HierarchyNodeRoleInline]

    fieldsets = (
        (None, {
            "fields": ("name", "slug", "code")
        }),
        ("Hierarchy", {
            "fields": ("hierarchy_type", "parent", "path", "depth")
        }),
        ("Tenant", {
            "fields": ("tenant_content_type", "tenant_object_id")
        }),
        ("Metadata", {
            "fields": ("metadata",),
            "classes": ("collapse",),
        }),
        ("Status", {
            "fields": ("is_active", "created_at", "updated_at")
        }),
    )

    def get_search_results(self, request, queryset, search_term):
        """Enable autocomplete for parent field."""
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        return queryset, use_distinct


@admin.register(HierarchyNodeRole)
class HierarchyNodeRoleAdmin(admin.ModelAdmin):
    """Admin for HierarchyNodeRole model (standalone view)."""

    list_display = ("node", "user", "role", "inheritable", "created_at")
    list_filter = ("role", "inheritable")
    search_fields = ("node__name", "user__username")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("node", "user")
