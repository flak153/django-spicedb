"""Signal handlers for GroupMembership tuple synchronization."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save

from django_rebac.adapters import factory
from django_rebac.adapters.base import TupleKey, TupleWrite


def _handle_membership_pre_save(sender, instance, **kwargs):
    """Track old membership values before save to detect changes."""
    if not instance.pk:
        return  # New membership, nothing to track

    from example_project.documents.models import GroupMembership

    try:
        old = GroupMembership.objects.only("group_id", "user_id", "role").get(pk=instance.pk)
        # Store on instance to avoid global dict issues (thread safety, id reuse)
        instance._rebac_old_values = {
            "group_id": old.group_id,
            "user_id": old.user_id,
            "role": old.role,
        }
    except GroupMembership.DoesNotExist:
        pass


def _handle_membership_post_save(sender, instance, created, **kwargs):
    """Write membership tuple to SpiceDB on save."""
    old_values = getattr(instance, "_rebac_old_values", None)

    # Clean up instance attribute
    if hasattr(instance, "_rebac_old_values"):
        delattr(instance, "_rebac_old_values")

    new_group_id = instance.group_id
    new_user_id = instance.user_id
    new_role = instance.role

    writes = []
    deletes = []

    if old_values:
        old_group_id = old_values["group_id"]
        old_user_id = old_values["user_id"]
        old_role = old_values["role"]

        # Check if anything changed
        tuple_changed = (
            old_group_id != new_group_id
            or old_user_id != new_user_id
            or old_role != new_role
        )

        if tuple_changed:
            # Delete old tuple
            deletes.append(
                TupleKey(
                    object=f"group:{old_group_id}",
                    relation=old_role,
                    subject=f"user:{old_user_id}",
                )
            )
    else:
        # New instance or no old values found - tuple definitely changed
        tuple_changed = True

    # Only write if something changed (or new instance)
    if created or (old_values and (
        old_values["group_id"] != new_group_id
        or old_values["user_id"] != new_user_id
        or old_values["role"] != new_role
    )) or not old_values:
        writes.append(
            TupleWrite(
                key=TupleKey(
                    object=f"group:{new_group_id}",
                    relation=new_role,
                    subject=f"user:{new_user_id}",
                )
            )
        )

    if not writes and not deletes:
        return  # Nothing to do

    def do_sync():
        adapter = factory.get_adapter()
        if deletes:
            adapter.delete_tuples(deletes)
        if writes:
            adapter.write_tuples(writes)

    transaction.on_commit(do_sync)


def _handle_membership_post_delete(sender, instance, **kwargs):
    """Delete membership tuple from SpiceDB on delete."""
    group_id = instance.group_id
    user_id = instance.user_id
    role = instance.role

    keys = [
        TupleKey(
            object=f"group:{group_id}",
            relation=role,
            subject=f"user:{user_id}",
        )
    ]

    def do_delete():
        factory.get_adapter().delete_tuples(keys)

    transaction.on_commit(do_delete)


def connect_group_membership_signals():
    """Connect signal handlers for GroupMembership model."""
    from example_project.documents.models import GroupMembership

    # Use dispatch_uid to prevent duplicate connections
    pre_save.connect(
        _handle_membership_pre_save,
        sender=GroupMembership,
        weak=False,
        dispatch_uid="rebac_membership_pre_save",
    )
    post_save.connect(
        _handle_membership_post_save,
        sender=GroupMembership,
        weak=False,
        dispatch_uid="rebac_membership_post_save",
    )
    post_delete.connect(
        _handle_membership_post_delete,
        sender=GroupMembership,
        weak=False,
        dispatch_uid="rebac_membership_post_delete",
    )
