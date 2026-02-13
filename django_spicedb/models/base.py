"""RebacModel base classes."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from django.db.models import Model as DjangoModel


class RebacModelBase(models.base.ModelBase):
    """
    Metaclass that registers Django models with RebacMeta.

    When a model class with a RebacMeta inner class is defined,
    this metaclass automatically registers it to the global registry.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple,
        namespace: dict,
        **kwargs: Any,
    ) -> "RebacModelBase":
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        # Don't register abstract models or the base RebacModel itself
        if hasattr(cls, '_meta') and not cls._meta.abstract:
            if hasattr(cls, 'RebacMeta'):
                from django_spicedb.core import register_rebac_model
                register_rebac_model(cls)

        return cls


class RebacModel(models.Model, metaclass=RebacModelBase):
    """
    Base class for Django models with ReBAC permissions.

    Models inheriting from RebacModel can define a RebacMeta inner class
    to configure relations and permissions:

        class Document(RebacModel):
            owner = models.ForeignKey(User, on_delete=models.CASCADE)
            folder = models.ForeignKey(Folder, on_delete=models.CASCADE)

            class RebacMeta:
                type_name = "document"  # optional, defaults to snake_case
                relations = {
                    "owner": "owner",    # relation_name: field_name
                    "parent": "folder",  # can rename
                }
                permissions = {
                    "view": "owner + parent->view",
                    "edit": "owner",
                }
    """

    class Meta:
        abstract = True

    def grant(self, subject: "DjangoModel | str", relation: str) -> None:
        """
        Grant a relation to a subject on this object.

        Args:
            subject: A Django model instance or "type:id" string
            relation: The relation name to grant
        """
        from ..adapters import get_adapter
        from ..adapters.base import TupleKey, TupleWrite
        from ..conf import get_type_for_model

        adapter = get_adapter()

        # Build object reference
        object_type = get_type_for_model(self.__class__)
        object_ref = f"{object_type}:{self.pk}"

        # Build subject reference
        if isinstance(subject, models.Model):
            subject_type = get_type_for_model(subject.__class__)
            subject_ref = f"{subject_type}:{subject.pk}"
        else:
            subject_ref = subject

        tuple_write = TupleWrite(
            key=TupleKey(
                object=object_ref,
                relation=relation,
                subject=subject_ref,
            )
        )
        adapter.write_tuples([tuple_write])

    def revoke(self, subject: "DjangoModel | str", relation: str) -> None:
        """
        Revoke a relation from a subject on this object.

        Args:
            subject: A Django model instance or "type:id" string
            relation: The relation name to revoke
        """
        from ..adapters import get_adapter
        from ..adapters.base import TupleKey
        from ..conf import get_type_for_model

        adapter = get_adapter()

        # Build object reference
        object_type = get_type_for_model(self.__class__)
        object_ref = f"{object_type}:{self.pk}"

        # Build subject reference
        if isinstance(subject, models.Model):
            subject_type = get_type_for_model(subject.__class__)
            subject_ref = f"{subject_type}:{subject.pk}"
        else:
            subject_ref = subject

        tuple_key = TupleKey(
            object=object_ref,
            relation=relation,
            subject=subject_ref,
        )
        adapter.delete_tuples([tuple_key])

    def has_perm(self, subject: "DjangoModel | str", permission: str) -> bool:
        """
        Check if a subject has a permission on this object.

        Args:
            subject: A Django model instance or "type:id" string
            permission: The permission to check

        Returns:
            True if the subject has the permission
        """
        from ..runtime import can
        return can(subject, permission, self)
