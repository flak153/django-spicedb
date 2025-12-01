"""
Signal handlers for hierarchy model tuple synchronization.

Automatically syncs HierarchyNode parent relationships and HierarchyNodeRole
assignments to SpiceDB tuples.
"""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save

from django_rebac.adapters import factory
from django_rebac.adapters.base import TupleKey, TupleWrite


_SIGNALS_CONNECTED = False


def connect_hierarchy_signals() -> None:
    """
    Connect signal handlers for hierarchy models.

    Call this in your app's ready() hook or after django_rebac is initialized.
    Safe to call multiple times - signals are only connected once.
    """
    global _SIGNALS_CONNECTED

    if _SIGNALS_CONNECTED:
        return

    from django_rebac.models import HierarchyNode, HierarchyNodeRole

    # HierarchyNode signals
    post_save.connect(_handle_hierarchy_node_save, sender=HierarchyNode, weak=False)
    post_delete.connect(_handle_hierarchy_node_delete, sender=HierarchyNode, weak=False)

    # HierarchyNodeRole signals
    post_save.connect(_handle_hierarchy_role_save, sender=HierarchyNodeRole, weak=False)
    post_delete.connect(_handle_hierarchy_role_delete, sender=HierarchyNodeRole, weak=False)

    _SIGNALS_CONNECTED = True


def disconnect_hierarchy_signals() -> None:
    """Disconnect hierarchy signal handlers. Primarily for testing."""
    global _SIGNALS_CONNECTED

    from django_rebac.models import HierarchyNode, HierarchyNodeRole

    post_save.disconnect(_handle_hierarchy_node_save, sender=HierarchyNode)
    post_delete.disconnect(_handle_hierarchy_node_delete, sender=HierarchyNode)
    post_save.disconnect(_handle_hierarchy_role_save, sender=HierarchyNodeRole)
    post_delete.disconnect(_handle_hierarchy_role_delete, sender=HierarchyNodeRole)

    _SIGNALS_CONNECTED = False


# =============================================================================
# HierarchyNode Signal Handlers
# =============================================================================


def _handle_hierarchy_node_save(sender, instance, **kwargs) -> None:
    """
    Handle HierarchyNode save - write parent tuple if parent exists.

    Writes tuple: hierarchy_node:{child_pk}#parent@hierarchy_node:{parent_pk}
    """
    if instance.parent_id is None:
        return

    tuple_write = TupleWrite(
        key=TupleKey(
            object=f"hierarchy_node:{instance.pk}",
            relation="parent",
            subject=f"hierarchy_node:{instance.parent_id}",
        )
    )

    try:
        adapter = factory.get_adapter()
        adapter.write_tuples([tuple_write])
    except Exception:
        # Log but don't fail the save
        pass


def _handle_hierarchy_node_delete(sender, instance, **kwargs) -> None:
    """
    Handle HierarchyNode delete - remove parent tuple if parent existed.

    Deletes tuple: hierarchy_node:{child_pk}#parent@hierarchy_node:{parent_pk}
    """
    # Use cached parent_id to avoid DB hit during cascade delete
    parent_id = instance.__dict__.get("parent_id")
    if parent_id is None:
        return

    tuple_key = TupleKey(
        object=f"hierarchy_node:{instance.pk}",
        relation="parent",
        subject=f"hierarchy_node:{parent_id}",
    )

    try:
        adapter = factory.get_adapter()
        adapter.delete_tuples([tuple_key])
    except Exception:
        # Log but don't fail the delete
        pass


# =============================================================================
# HierarchyNodeRole Signal Handlers
# =============================================================================


def _handle_hierarchy_role_save(sender, instance, **kwargs) -> None:
    """
    Handle HierarchyNodeRole save - write role tuple.

    Writes tuple: hierarchy_node:{node_pk}#{role}@user:{user_pk}
    """
    tuple_write = TupleWrite(
        key=TupleKey(
            object=f"hierarchy_node:{instance.node_id}",
            relation=instance.role,
            subject=f"user:{instance.user_id}",
        )
    )

    try:
        adapter = factory.get_adapter()
        adapter.write_tuples([tuple_write])
    except Exception:
        # Log but don't fail the save
        pass


def _handle_hierarchy_role_delete(sender, instance, **kwargs) -> None:
    """
    Handle HierarchyNodeRole delete - remove role tuple.

    Deletes tuple: hierarchy_node:{node_pk}#{role}@user:{user_pk}
    """
    # Use cached IDs to avoid DB hits during cascade delete
    node_id = instance.__dict__.get("node_id")
    user_id = instance.__dict__.get("user_id")
    role = instance.role

    if node_id is None or user_id is None:
        return

    tuple_key = TupleKey(
        object=f"hierarchy_node:{node_id}",
        relation=role,
        subject=f"user:{user_id}",
    )

    try:
        adapter = factory.get_adapter()
        adapter.delete_tuples([tuple_key])
    except Exception:
        # Log but don't fail the delete
        pass
