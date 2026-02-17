"""Tuple synchronization registry for Django models."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Tuple

from django.db import transaction
from django.db.models import Model
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.utils.module_loading import import_string

import django_spicedb.conf as conf
from django_spicedb.adapters import factory
from django_spicedb.adapters.base import TupleKey, TupleWrite
from django_spicedb.types.graph import TypeConfig


# Instance attribute key for storing old FK values
_FK_CACHE_KEY = "_rebac_old_fk_values"

# Instance attribute key for storing old through-table values
_THROUGH_CACHE_KEY = "_rebac_old_through_values"


@dataclass
class _RegisteredSignal:
    model: type[Model]
    pre_save_handler: Callable[..., None]
    post_save_handler: Callable[..., None]
    delete_handler: Callable[..., None]
    m2m_handlers: List[Tuple[type[Model], Callable[..., None]]]
    dispatch_uids: List[Tuple[str, type[Model]]] = field(default_factory=list)


@dataclass
class _RegisteredThroughSignal:
    model: type[Model]
    pre_save_handler: Callable[..., None]
    post_save_handler: Callable[..., None]
    delete_handler: Callable[..., None]
    object_fk: str = ""
    subject_fk: str = ""
    role_field: str = ""
    role_mapping: Dict[str, tuple] = field(default_factory=dict)
    dispatch_uids: List[Tuple[str, type[Model]]] = field(default_factory=list)


_REGISTERED: Dict[type[Model], _RegisteredSignal] = {}
_THROUGH_REGISTERED: Dict[type[Model], _RegisteredThroughSignal] = {}


def refresh() -> None:
    """Rebuild the signal registry from the current type graph."""

    _disconnect_all()

    graph = conf.get_type_graph()
    for type_cfg in graph.types.values():
        if not type_cfg.model or not type_cfg.bindings:
            continue
        model = import_string(type_cfg.model)
        _register_model(type_cfg.name, model, type_cfg)

    _register_through_bindings(graph)


def _disconnect_all() -> None:
    for registered in list(_REGISTERED.values()):
        for uid, sender in registered.dispatch_uids:
            pre_save.disconnect(sender=sender, dispatch_uid=uid)
            post_save.disconnect(sender=sender, dispatch_uid=uid)
            post_delete.disconnect(sender=sender, dispatch_uid=uid)
            m2m_changed.disconnect(sender=sender, dispatch_uid=uid)
    _REGISTERED.clear()

    for registered in list(_THROUGH_REGISTERED.values()):
        for uid, sender in registered.dispatch_uids:
            pre_save.disconnect(sender=sender, dispatch_uid=uid)
            post_save.disconnect(sender=sender, dispatch_uid=uid)
            post_delete.disconnect(sender=sender, dispatch_uid=uid)
    _THROUGH_REGISTERED.clear()


def _register_model(type_name: str, model: type[Model], cfg: TypeConfig) -> None:
    # Get list of FK fields we need to track for change detection
    fk_fields = []
    for relation_name, binding_config in cfg.bindings.items():
        if binding_config.get("kind") == "fk":
            field_name = binding_config.get("field")
            if field_name:
                fk_fields.append((relation_name, field_name, binding_config))

    def handle_pre_save(sender, instance: Model, **kwargs) -> None:  # pragma: no cover
        """Track old FK values before save to detect changes."""
        if not instance.pk:
            return  # New instance, nothing to track

        if not fk_fields:
            return  # No FK fields to track

        # If update_fields is specified and no binding fields are included, skip
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            binding_field_names = set()
            for _, field_name, _ in fk_fields:
                binding_field_names.add(field_name)
                binding_field_names.add(f"{field_name}_id")
            if not binding_field_names.intersection(update_fields):
                return  # No binding fields being updated

        old_values = {}

        # Always fetch from database - by pre_save, instance.__dict__ has new values
        try:
            # Collect all fields we need to fetch
            fields_to_fetch = set()
            for _, field_name, binding_config in fk_fields:
                fields_to_fetch.add(field_name)
                # Also fetch object_field if it's an FK (not "pk")
                object_field = binding_config.get("object_field", "pk")
                if object_field != "pk":
                    fields_to_fetch.add(object_field)

            db_instance = model.objects.only(*fields_to_fetch).get(pk=instance.pk)

            for relation_name, field_name, binding_config in fk_fields:
                subject_field = binding_config.get("subject_field", "pk")
                object_field = binding_config.get("object_field", "pk")

                # Get old subject value
                if subject_field == "pk":
                    # Simple case: use FK ID directly
                    old_subject = getattr(db_instance, f"{field_name}_id", None)
                else:
                    # Need to get attribute from related object
                    related = getattr(db_instance, field_name, None)
                    old_subject = getattr(related, subject_field, None) if related else None

                # Get old object value
                if object_field == "pk":
                    old_object = db_instance.pk
                else:
                    # object_field refers to another FK on this instance
                    old_object = _get_fk_value(db_instance, object_field, "pk")

                old_values[relation_name] = {
                    "subject": old_subject,
                    "object": old_object,
                }
        except model.DoesNotExist:
            pass

        if old_values:
            # Store on instance to avoid global dict issues (thread safety, id reuse)
            setattr(instance, _FK_CACHE_KEY, old_values)

    def handle_post_save(sender, instance: Model, **kwargs) -> None:  # pragma: no cover
        """Write new tuples and delete old ones if FK changed."""
        old_values = getattr(instance, _FK_CACHE_KEY, {})
        # Clean up instance attribute
        if hasattr(instance, _FK_CACHE_KEY):
            delattr(instance, _FK_CACHE_KEY)

        # If update_fields is specified and no binding fields are included, skip sync
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            binding_field_names = set()
            for _, field_name, _ in fk_fields:
                binding_field_names.add(field_name)
                binding_field_names.add(f"{field_name}_id")
            if not binding_field_names.intersection(update_fields):
                return  # No binding fields being updated

        writes = list(_gather_tuple_writes(type_name, cfg, instance))
        deletes = []

        # Check for FK changes and queue deletions for old values
        for relation_name, field_name, binding_config in fk_fields:
            old_data = old_values.get(relation_name, {})
            old_subject = old_data.get("subject")
            old_object = old_data.get("object")

            # Get new values
            subject_field = binding_config.get("subject_field", "pk")
            object_field = binding_config.get("object_field", "pk")

            new_subject = _get_fk_value(instance, field_name, subject_field)
            if object_field == "pk":
                new_object = instance.pk
            else:
                new_object = _get_fk_value(instance, object_field, "pk")

            # Check if tuple changed - only delete if we had valid old values
            # (both subject and object must be non-None to have written a tuple)
            if (
                old_subject is not None
                and old_object is not None
                and (old_subject != new_subject or old_object != new_object)
            ):
                # FK changed - delete old tuple
                relation_target = cfg.relations.get(relation_name)
                if relation_target:
                    subject_type, subject_relation = _parse_subject(relation_target)
                    deletes.append(TupleKey(
                        object=f"{type_name}:{old_object}",
                        relation=relation_name,
                        subject=_format_subject(subject_type, old_subject, subject_relation),
                    ))

        # Wrap in transaction.on_commit to avoid phantom tuples on rollback
        def do_sync():
            adapter = factory.get_adapter()
            if deletes:
                adapter.delete_tuples(deletes)
            if writes:
                adapter.write_tuples(writes)

        transaction.on_commit(do_sync)

    def handle_delete(sender, instance: Model, **kwargs) -> None:  # pragma: no cover
        keys = list(_gather_tuple_keys(type_name, cfg, instance))
        if not keys:
            return

        # Wrap in transaction.on_commit
        def do_delete():
            factory.get_adapter().delete_tuples(keys)

        transaction.on_commit(do_delete)

    # Use dispatch_uid to prevent duplicate connections
    uids: List[Tuple[str, type[Model]]] = []

    pre_uid = f"rebac_pre_save_{type_name}"
    post_uid = f"rebac_post_save_{type_name}"
    del_uid = f"rebac_post_delete_{type_name}"

    pre_save.connect(
        handle_pre_save, sender=model, weak=False,
        dispatch_uid=pre_uid,
    )
    post_save.connect(
        handle_post_save, sender=model, weak=False,
        dispatch_uid=post_uid,
    )
    post_delete.connect(
        handle_delete, sender=model, weak=False,
        dispatch_uid=del_uid,
    )
    uids.extend([(pre_uid, model), (post_uid, model), (del_uid, model)])

    m2m_handlers: List[Tuple[type[Model], Callable[..., None]]] = []
    for relation_name, binding_config in cfg.bindings.items():
        if binding_config.get("kind") != "m2m":
            continue
        relation_target = cfg.relations.get(relation_name)
        if relation_target is None:
            continue
        field_name = binding_config.get("field")
        if not field_name:
            continue
        field = model._meta.get_field(field_name)
        through_model = field.remote_field.through  # type: ignore[attr-defined]

        handler = _make_m2m_handler(
            type_name,
            relation_name,
            relation_target,
            binding_config,
        )
        m2m_uid = f"rebac_m2m_{type_name}_{relation_name}"
        m2m_changed.connect(
            handler, sender=through_model, weak=False,
            dispatch_uid=m2m_uid,
        )
        m2m_handlers.append((through_model, handler))
        uids.append((m2m_uid, through_model))

    _REGISTERED[model] = _RegisteredSignal(
        model, handle_pre_save, handle_post_save, handle_delete, m2m_handlers, uids,
    )


def _gather_tuple_writes(type_name: str, cfg: TypeConfig, instance: Model) -> Iterable[TupleWrite]:
    for relation_name, binding_config in cfg.bindings.items():
        relation_target = cfg.relations.get(relation_name)
        if relation_target is None:
            continue
        kind = binding_config.get("kind")
        field_name = binding_config.get("field")
        if kind != "fk" or not field_name:
            continue
        subject_id = _get_fk_value(instance, field_name, binding_config.get("subject_field", "pk"))
        if subject_id is None:
            continue
        subject_type, subject_relation = _parse_subject(relation_target)
        if subject_id is None:
            continue

        object_field_name = binding_config.get("object_field", "pk")
        if object_field_name == "pk":
            object_id = instance.pk
        else:
            object_id = _get_fk_value(instance, object_field_name, "pk")
        if object_id is None:
            continue

        yield TupleWrite(
            key=TupleKey(
                object=f"{type_name}:{object_id}",
                relation=relation_name,
                subject=_format_subject(subject_type, subject_id, subject_relation),
            )
        )


def _gather_tuple_keys(type_name: str, cfg: TypeConfig, instance: Model) -> Iterable[TupleKey]:
    for tuple_write in _gather_tuple_writes(type_name, cfg, instance):
        yield tuple_write.key


def _parse_subject(target: str) -> tuple[str, str | None]:
    if "#" in target:
        subject_type, relation = target.split("#", 1)
        return subject_type, relation
    return target, None


def _format_subject(subject_type: str, subject_id: object, relation: str | None) -> str:
    value = f"{subject_type}:{subject_id}"
    if relation:
        value = f"{value}#{relation}"
    return value


def _make_m2m_handler(
    type_name: str,
    relation_name: str,
    relation_target: str,
    binding_config: dict,
):
    subject_type, subject_relation = _parse_subject(relation_target)
    object_field = binding_config.get("object_field", "pk")
    field_name = binding_config.get("field")

    # Cache key for storing pre_clear IDs on the instance
    clear_cache_key = f"_rebac_m2m_clear_{relation_name}"

    def handler(sender, instance, action, reverse, model, pk_set, **kwargs):  # pragma: no cover - signal hook
        if reverse:
            return

        # Handle pre_clear: capture IDs before they're removed
        if action == "pre_clear":
            related_manager = getattr(instance, field_name)
            pks_to_clear = list(related_manager.values_list("pk", flat=True))
            if pks_to_clear:
                setattr(instance, clear_cache_key, pks_to_clear)
            return

        if action not in {"post_add", "post_remove", "post_clear"}:
            return

        object_id = getattr(instance, object_field, None)
        if object_id is None:
            return

        if action == "post_add":
            writes = [
                TupleWrite(
                    key=TupleKey(
                        object=f"{type_name}:{object_id}",
                        relation=relation_name,
                        subject=_format_subject(subject_type, pk, subject_relation),
                    )
                )
                for pk in pk_set
            ]
            if writes:
                def do_write():
                    factory.get_adapter().write_tuples(writes)
                transaction.on_commit(do_write)
        elif action == "post_remove":
            keys = [
                TupleKey(
                    object=f"{type_name}:{object_id}",
                    relation=relation_name,
                    subject=_format_subject(subject_type, pk, subject_relation),
                )
                for pk in pk_set
            ]
            if keys:
                def do_delete():
                    factory.get_adapter().delete_tuples(keys)
                transaction.on_commit(do_delete)
        elif action == "post_clear":
            # Get IDs captured during pre_clear
            pk_iterable = getattr(instance, clear_cache_key, [])
            # Clean up the cache
            if hasattr(instance, clear_cache_key):
                delattr(instance, clear_cache_key)

            keys = [
                TupleKey(
                    object=f"{type_name}:{object_id}",
                    relation=relation_name,
                    subject=_format_subject(subject_type, pk, subject_relation),
                )
                for pk in pk_iterable
            ]
            if keys:
                def do_delete():
                    factory.get_adapter().delete_tuples(keys)
                transaction.on_commit(do_delete)

    return handler


def _get_fk_value(instance: Model, field_name: str, attribute: str) -> object | None:
    if attribute != "pk":
        related = getattr(instance, field_name, None)
        if related is None:
            return None
        return getattr(related, attribute, None)
    # Use the cached _id to avoid database hits during delete cascades.
    cache_key = f"{field_name}_id"
    if cache_key in instance.__dict__:
        return instance.__dict__[cache_key]
    related = getattr(instance, field_name, None)
    if related is None:
        return None
    return getattr(related, attribute, None)


# ------------------------------------------------------------------ through-table support


def _register_through_bindings(graph) -> None:
    """Scan all type configs for through bindings and register signal handlers.

    Multiple relations on the same type may share a through model (e.g.
    member/manager both use GroupMembership). We aggregate them into a single
    set of handlers per through model to avoid duplicate signals.
    """
    # Aggregate: through_model_path -> {role_value: [(type_name, relation_name, subject_type)]}
    aggregated: Dict[str, Dict[str, str]] = defaultdict(dict)
    # Track per-model metadata (object_fk, subject_fk, role_field)
    model_meta: Dict[str, Dict[str, str]] = {}

    for type_name, type_cfg in graph.types.items():
        for relation_name, binding_config in type_cfg.bindings.items():
            if binding_config.get("kind") != "through":
                continue

            through_model_path = binding_config.get("model", "")
            if not through_model_path:
                continue

            object_fk = binding_config.get("object_fk", "")
            subject_fk = binding_config.get("subject_fk", "")
            role_field = binding_config.get("role_field", "")
            role_value = binding_config.get("role_value", "")

            relation_target = type_cfg.relations.get(relation_name, "")
            subject_type, subject_relation = _parse_subject(relation_target)

            # Store role_value -> (type_name, relation_name, subject_type, subject_relation)
            aggregated[through_model_path][role_value] = (
                type_name, relation_name, subject_type, subject_relation
            )

            if through_model_path not in model_meta:
                model_meta[through_model_path] = {
                    "object_fk": object_fk,
                    "subject_fk": subject_fk,
                    "role_field": role_field,
                }

    for through_model_path, role_mapping in aggregated.items():
        meta = model_meta[through_model_path]
        through_model = import_string(through_model_path)

        handlers = _make_through_handlers(
            through_model=through_model,
            object_fk=meta["object_fk"],
            subject_fk=meta["subject_fk"],
            role_field=meta["role_field"],
            role_mapping=role_mapping,
        )

        pre_save_handler, post_save_handler, post_delete_handler = handlers

        uid_prefix = f"rebac_through_{through_model_path}"
        pre_uid = f"{uid_prefix}_pre_save"
        post_uid = f"{uid_prefix}_post_save"
        del_uid = f"{uid_prefix}_post_delete"

        pre_save.connect(
            pre_save_handler, sender=through_model, weak=False,
            dispatch_uid=pre_uid,
        )
        post_save.connect(
            post_save_handler, sender=through_model, weak=False,
            dispatch_uid=post_uid,
        )
        post_delete.connect(
            post_delete_handler, sender=through_model, weak=False,
            dispatch_uid=del_uid,
        )

        through_uids = [
            (pre_uid, through_model),
            (post_uid, through_model),
            (del_uid, through_model),
        ]

        _THROUGH_REGISTERED[through_model] = _RegisteredThroughSignal(
            model=through_model,
            pre_save_handler=pre_save_handler,
            post_save_handler=post_save_handler,
            delete_handler=post_delete_handler,
            object_fk=meta["object_fk"],
            subject_fk=meta["subject_fk"],
            role_field=meta["role_field"],
            role_mapping=role_mapping,
            dispatch_uids=through_uids,
        )


def _make_through_handlers(
    through_model: type[Model],
    object_fk: str,
    subject_fk: str,
    role_field: str,
    role_mapping: Dict[str, tuple],
) -> Tuple[Callable, Callable, Callable]:
    """Create pre_save, post_save, post_delete handlers for a through model.

    role_mapping: {role_value: (type_name, relation_name, subject_type, subject_relation)}
    """

    object_fk_id = f"{object_fk}_id"
    subject_fk_id = f"{subject_fk}_id"

    def _build_tuple_key(obj_id, subj_id, role_value):
        """Build a TupleKey from the through-table row values."""
        entry = role_mapping.get(role_value)
        if entry is None:
            return None
        type_name, relation_name, subject_type, subject_relation = entry
        return TupleKey(
            object=f"{type_name}:{obj_id}",
            relation=relation_name,
            subject=_format_subject(subject_type, subj_id, subject_relation),
        )

    def handle_pre_save(sender, instance, **kwargs):  # pragma: no cover
        """Track old values before save to detect changes."""
        if not instance.pk:
            return

        try:
            old = through_model.objects.only(
                object_fk_id, subject_fk_id, role_field,
            ).get(pk=instance.pk)
            setattr(instance, _THROUGH_CACHE_KEY, {
                "object_id": getattr(old, object_fk_id),
                "subject_id": getattr(old, subject_fk_id),
                "role": getattr(old, role_field),
            })
        except through_model.DoesNotExist:
            pass

    def handle_post_save(sender, instance, created, **kwargs):  # pragma: no cover
        """Write new tuple, delete old if changed."""
        old_values = getattr(instance, _THROUGH_CACHE_KEY, None)
        if hasattr(instance, _THROUGH_CACHE_KEY):
            delattr(instance, _THROUGH_CACHE_KEY)

        new_obj_id = getattr(instance, object_fk_id)
        new_subj_id = getattr(instance, subject_fk_id)
        new_role = getattr(instance, role_field)

        if new_obj_id is None or new_subj_id is None:
            return

        writes: list[TupleWrite] = []
        deletes: list[TupleKey] = []

        if old_values:
            old_obj_id = old_values["object_id"]
            old_subj_id = old_values["subject_id"]
            old_role = old_values["role"]

            changed = (
                old_obj_id != new_obj_id
                or old_subj_id != new_subj_id
                or old_role != new_role
            )

            if not changed:
                return  # No-op save

            # Delete old tuple
            old_key = _build_tuple_key(old_obj_id, old_subj_id, old_role)
            if old_key:
                deletes.append(old_key)

        # Write new tuple
        new_key = _build_tuple_key(new_obj_id, new_subj_id, new_role)
        if new_key:
            writes.append(TupleWrite(key=new_key))

        if not writes and not deletes:
            return

        def do_sync():
            adapter = factory.get_adapter()
            if deletes:
                adapter.delete_tuples(deletes)
            if writes:
                adapter.write_tuples(writes)

        transaction.on_commit(do_sync)

    def handle_post_delete(sender, instance, **kwargs):  # pragma: no cover
        """Delete tuple on row deletion."""
        obj_id = getattr(instance, object_fk_id, None)
        subj_id = getattr(instance, subject_fk_id, None)
        role = getattr(instance, role_field, None)

        if obj_id is None or subj_id is None:
            return

        key = _build_tuple_key(obj_id, subj_id, role)
        if not key:
            return

        def do_delete():
            factory.get_adapter().delete_tuples([key])

        transaction.on_commit(do_delete)

    return handle_pre_save, handle_post_save, handle_post_delete


# ------------------------------------------------------------------ bulk sync utilities


def sync_instances(instances: List[Model]) -> None:
    """Compute and write tuples for a list of Django model instances.

    This is useful after bulk_create() or when you need to manually sync
    a batch of already-saved instances (with PKs assigned).

    Example:
        objs = Document.objects.bulk_create([Document(owner=user1), Document(owner=user2)])
        sync_instances(objs)

    Args:
        instances: List of Django model instances (must be saved with PKs).
    """
    if not instances:
        return

    # Group instances by model type
    by_model: Dict[type[Model], List[Model]] = defaultdict(list)
    for instance in instances:
        by_model[type(instance)].append(instance)

    all_writes: List[TupleWrite] = []

    for model, model_instances in by_model.items():
        # Look up the type name and config for this model
        type_name = conf.get_type_for_model(model)
        if not type_name:
            continue

        graph = conf.get_type_graph()
        cfg = graph.types.get(type_name)
        if not cfg or not cfg.bindings:
            continue

        # Gather tuples for each instance
        for instance in model_instances:
            all_writes.extend(_gather_tuple_writes(type_name, cfg, instance))

    if not all_writes:
        return

    # Defer write until transaction commits
    def do_sync():
        factory.get_adapter().write_tuples(all_writes)

    transaction.on_commit(do_sync)


def sync_through_instances(instances: List[Model]) -> None:
    """Compute and write tuples for through-table model instances.

    This is useful after bulk_create() on a through-table model (e.g. GroupMembership).

    Example:
        memberships = GroupMembership.objects.bulk_create([
            GroupMembership(group=group1, user=user1, role='member'),
            GroupMembership(group=group1, user=user2, role='manager'),
        ])
        sync_through_instances(memberships)

    Args:
        instances: List of through-table model instances (must be saved with PKs).
    """
    if not instances:
        return

    # Group instances by model type
    by_model: Dict[type[Model], List[Model]] = defaultdict(list)
    for instance in instances:
        by_model[type(instance)].append(instance)

    all_writes: List[TupleWrite] = []

    for model, model_instances in by_model.items():
        # Look up through-table registration metadata
        registered = _THROUGH_REGISTERED.get(model)
        if not registered or not registered.role_mapping:
            continue

        object_fk_id = f"{registered.object_fk}_id"
        subject_fk_id = f"{registered.subject_fk}_id"
        role_field = registered.role_field

        # Build tuple for each instance
        for instance in model_instances:
            obj_id = getattr(instance, object_fk_id, None)
            subj_id = getattr(instance, subject_fk_id, None)
            role_value = getattr(instance, role_field, None)

            if obj_id is None or subj_id is None:
                continue

            entry = registered.role_mapping.get(role_value)
            if entry is None:
                continue

            type_name, relation_name, subject_type, subject_relation = entry
            key = TupleKey(
                object=f"{type_name}:{obj_id}",
                relation=relation_name,
                subject=_format_subject(subject_type, subj_id, subject_relation),
            )
            all_writes.append(TupleWrite(key=key))

    if not all_writes:
        return

    # Defer write until transaction commits
    def do_sync():
        factory.get_adapter().write_tuples(all_writes)

    transaction.on_commit(do_sync)


def _sync_queryset_update_impl(queryset, raw_update_fn, **updated_fields) -> int:
    """Core implementation for syncing tuples after a QuerySet update.

    Accepts a raw update callable to avoid recursion when called from
    RebacQuerySet.update().

    Args:
        queryset: Django QuerySet to update.
        raw_update_fn: Callable that performs the actual DB update.
        **updated_fields: Field assignments to pass to the update callable.

    Returns:
        Number of rows updated.
    """
    model = queryset.model

    # Look up type name and config
    type_name = conf.get_type_for_model(model)
    if not type_name:
        return raw_update_fn(**updated_fields)

    graph = conf.get_type_graph()
    cfg = graph.types.get(type_name)
    if not cfg or not cfg.bindings:
        return raw_update_fn(**updated_fields)

    # Collect FK field names that are bound to relations
    fk_field_names = set()
    for relation_name, binding_config in cfg.bindings.items():
        if binding_config.get("kind") == "fk":
            field_name = binding_config.get("field")
            if field_name:
                fk_field_names.add(field_name)
                fk_field_names.add(f"{field_name}_id")

    # Check if any of the updated fields are FK bindings
    updated_field_names = set(updated_fields.keys())
    affected_fk_fields = fk_field_names.intersection(updated_field_names)

    if not affected_fk_fields:
        return raw_update_fn(**updated_fields)

    # Snapshot old values (PKs + all FK fields we care about)
    fields_to_fetch = {"pk"} | fk_field_names
    old_rows = list(queryset.values(*fields_to_fetch))

    if not old_rows:
        return 0

    # Perform the update
    updated_count = raw_update_fn(**updated_fields)

    if updated_count == 0:
        return 0

    # Re-fetch updated rows
    pks = [row["pk"] for row in old_rows]
    new_rows = list(model.objects.filter(pk__in=pks).values(*fields_to_fetch))

    # Build a mapping: pk -> row data
    old_by_pk = {row["pk"]: row for row in old_rows}
    new_by_pk = {row["pk"]: row for row in new_rows}

    # Compute tuple diffs
    deletes: List[TupleKey] = []
    writes: List[TupleWrite] = []

    for pk in pks:
        old_row = old_by_pk.get(pk)
        new_row = new_by_pk.get(pk)
        if not old_row or not new_row:
            continue

        for relation_name, binding_config in cfg.bindings.items():
            if binding_config.get("kind") != "fk":
                continue

            field_name = binding_config.get("field")
            if not field_name:
                continue

            object_field = binding_config.get("object_field", "pk")
            subject_field = binding_config.get("subject_field", "pk")

            if subject_field != "pk":
                continue

            fk_id_field = f"{field_name}_id"
            old_subject_id = old_row.get(fk_id_field)
            new_subject_id = new_row.get(fk_id_field)

            if object_field == "pk":
                object_id = pk
            else:
                object_id = pk

            if old_subject_id != new_subject_id:
                relation_target = cfg.relations.get(relation_name)
                if not relation_target:
                    continue

                subject_type, subject_relation = _parse_subject(relation_target)

                if old_subject_id is not None and object_id is not None:
                    deletes.append(TupleKey(
                        object=f"{type_name}:{object_id}",
                        relation=relation_name,
                        subject=_format_subject(subject_type, old_subject_id, subject_relation),
                    ))

                if new_subject_id is not None and object_id is not None:
                    writes.append(TupleWrite(key=TupleKey(
                        object=f"{type_name}:{object_id}",
                        relation=relation_name,
                        subject=_format_subject(subject_type, new_subject_id, subject_relation),
                    )))

    if deletes or writes:
        def do_sync():
            adapter = factory.get_adapter()
            if deletes:
                adapter.delete_tuples(deletes)
            if writes:
                adapter.write_tuples(writes)

        transaction.on_commit(do_sync)

    return updated_count


def sync_queryset_update(queryset, **updated_fields) -> int:
    """Sync tuples after a QuerySet.update() operation.

    This utility snapshots affected rows before the update, performs the update,
    re-fetches updated rows, computes tuple diffs, and syncs them to SpiceDB.

    Example:
        updated_count = sync_queryset_update(
            Document.objects.filter(project=old_project),
            project=new_project
        )

    Args:
        queryset: Django QuerySet to update.
        **updated_fields: Field assignments to pass to queryset.update().

    Returns:
        Number of rows updated (same as queryset.update() would return).
    """
    return _sync_queryset_update_impl(queryset, queryset.update, **updated_fields)
