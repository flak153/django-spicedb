"""Tuple synchronization registry for Django models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Tuple

from django.db.models import Model
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.utils.module_loading import import_string

import django_rebac.conf as conf
from django_rebac.adapters import factory
from django_rebac.adapters.base import TupleKey, TupleWrite
from django_rebac.types.graph import TypeConfig


@dataclass
class _RegisteredSignal:
    model: type[Model]
    save_handler: Callable[..., None]
    delete_handler: Callable[..., None]
    m2m_handlers: List[Tuple[type[Model], Callable[..., None]]]


_REGISTERED: Dict[type[Model], _RegisteredSignal] = {}


def refresh() -> None:
    """Rebuild the signal registry from the current type graph."""

    _disconnect_all()

    graph = conf.get_type_graph()
    for type_cfg in graph.types.values():
        if not type_cfg.model or not type_cfg.bindings:
            continue
        model = import_string(type_cfg.model)
        _register_model(type_cfg.name, model, type_cfg)


def _disconnect_all() -> None:
    for registered in list(_REGISTERED.values()):
        post_save.disconnect(registered.save_handler, sender=registered.model)
        post_delete.disconnect(registered.delete_handler, sender=registered.model)
        for sender, handler in registered.m2m_handlers:
            m2m_changed.disconnect(handler, sender=sender)
    _REGISTERED.clear()


def _register_model(type_name: str, model: type[Model], cfg: TypeConfig) -> None:
    def handle_save(sender, instance: Model, **kwargs) -> None:  # pragma: no cover - invoked via Django
        writes = list(_gather_tuple_writes(type_name, cfg, instance))
        if not writes:
            return
        factory.get_adapter().write_tuples(writes)

    def handle_delete(sender, instance: Model, **kwargs) -> None:  # pragma: no cover
        keys = list(_gather_tuple_keys(type_name, cfg, instance))
        if not keys:
            return
        factory.get_adapter().delete_tuples(keys)

    post_save.connect(handle_save, sender=model, weak=False)
    post_delete.connect(handle_delete, sender=model, weak=False)

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
        m2m_changed.connect(handler, sender=through_model, weak=False)
        m2m_handlers.append((through_model, handler))

    _REGISTERED[model] = _RegisteredSignal(model, handle_save, handle_delete, m2m_handlers)


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

    def handler(sender, instance, action, reverse, model, pk_set, **kwargs):  # pragma: no cover - signal hook
        if reverse:
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
                factory.get_adapter().write_tuples(writes)
        else:
            if action == "post_clear" and not pk_set:
                related_manager = getattr(instance, field_name)
                pk_iterable = related_manager.values_list("pk", flat=True)
            else:
                pk_iterable = pk_set
            keys = [
                TupleKey(
                    object=f"{type_name}:{object_id}",
                    relation=relation_name,
                    subject=_format_subject(subject_type, pk, subject_relation),
                )
                for pk in pk_iterable
            ]
            if keys:
                factory.get_adapter().delete_tuples(keys)

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
