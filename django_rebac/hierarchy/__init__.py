"""Multi-tenant hierarchy support for django-spicedb."""

from django_rebac.hierarchy.signals import connect_hierarchy_signals

__all__ = ["connect_hierarchy_signals"]
