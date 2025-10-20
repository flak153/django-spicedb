"""Minimal TypeGraph implementation used in early tests.

The goal is not to be feature complete but to provide a concrete object that
can validate a toy configuration and render a tiny SpiceDB-like schema string.
This gives us something executable for unit tests while the broader design in
``planning.md`` evolves into fuller modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, MutableMapping, Set


class TypeGraphError(ValueError):
    """Base error raised when a type configuration is invalid."""


class UnknownParentError(TypeGraphError):
    """Raised when a type references a parent that is not defined."""


class UnknownRelationSubject(TypeGraphError):
    """Raised when a relation subject references an unknown type."""


class InvalidPermissionExpression(TypeGraphError):
    """Raised when a permission references an unknown relation or permission."""


@dataclass(frozen=True)
class TypeConfig:
    """Simple in-memory representation of a type declaration."""

    name: str
    relations: Mapping[str, str] = field(default_factory=dict)
    permissions: Mapping[str, str] = field(default_factory=dict)
    parents: Iterable[str] = field(default_factory=tuple)
    bindings: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


_PERMISSION_TOKEN_DELIMS = re.compile(r"[|&()!]")
_PERMISSION_ARROW = re.compile(r"->")


class TypeGraph:
    """Registry of ``TypeConfig`` objects with lightweight validation."""

    ALLOWED_BINDING_KINDS: Set[str] = frozenset({"fk", "m2m", "through", "manual"})

    def __init__(
        self, types: Mapping[str, Mapping[str, object]] | None = None
    ) -> None:
        self._raw: Dict[str, Mapping[str, object]] = dict(types or {})
        self._types: Dict[str, TypeConfig] = {}
        self._build()

    # --------------------------------------------------------------------- API
    @property
    def types(self) -> Mapping[str, TypeConfig]:
        """Return a read-only view of the registered types."""

        return dict(self._types)

    def compile_schema(self) -> str:
        """Return a tiny SpiceDB-flavoured schema for the registered types."""

        sections: list[str] = []
        for name in sorted(self._types):
            cfg = self._types[name]
            lines: list[str] = [f"type {cfg.name}"]
            if cfg.relations:
                lines.append("  relations")
                for rel_name, subject in sorted(cfg.relations.items()):
                    lines.append(f"    define {rel_name}: {subject}")
            if cfg.permissions:
                lines.append("  permissions")
                for perm_name, expression in sorted(cfg.permissions.items()):
                    lines.append(f"    define {perm_name}: {expression}")
            if cfg.parents:
                lines.append("  parents")
                for parent in sorted(cfg.parents):
                    lines.append(f"    {parent}")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    # ------------------------------------------------------------------ internals
    def _build(self) -> None:
        for name, raw_cfg in self._raw.items():
            self._types[name] = TypeConfig(
                name=name,
                relations=self._extract_section(raw_cfg, "relations"),
                permissions=self._extract_section(raw_cfg, "permissions"),
                parents=tuple(self._extract_iterable(raw_cfg, "parents")),
                bindings=self._extract_bindings(raw_cfg),
            )
        self._validate_parents()
        self._validate_parent_cycles()
        self._validate_relation_subjects()
        self._validate_permission_expressions()
        self._validate_bindings()

    @staticmethod
    def _extract_section(
        cfg: Mapping[str, object], key: str
    ) -> MutableMapping[str, str]:
        section = cfg.get(key, {})
        if not section:
            return {}
        if not isinstance(section, Mapping):
            raise TypeGraphError(f"{key!r} must be a mapping.")
        result: Dict[str, str] = {}
        for k, v in section.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise TypeGraphError(f"{key!r} entries must be string → string.")
            result[k] = v
        return result

    def _extract_bindings(
        self, cfg: Mapping[str, object], key: str = "bindings"
    ) -> MutableMapping[str, MutableMapping[str, str]]:
        section = cfg.get(key, {})
        if not section:
            return {}
        if not isinstance(section, Mapping):
            raise TypeGraphError(f"{key!r} must be a mapping.")
        result: Dict[str, MutableMapping[str, str]] = {}
        for relation, binding in section.items():
            if not isinstance(relation, str):
                raise TypeGraphError(f"{key!r} keys must be strings.")
            if not isinstance(binding, Mapping):
                raise TypeGraphError(
                    f"{key!r}.{relation} must be a mapping with field/kind."
                )
            try:
                field_name = binding["field"]
                kind = binding["kind"]
            except KeyError as exc:
                raise TypeGraphError(
                    f"{key!r}.{relation} missing required key {exc.args[0]!r}"
                ) from exc
            if not isinstance(field_name, str) or not isinstance(kind, str):
                raise TypeGraphError(
                    f"{key!r}.{relation} field/kind must be strings."
                )
            lower_kind = kind.lower()
            if lower_kind not in self.ALLOWED_BINDING_KINDS:
                raise TypeGraphError(
                    f"{key!r}.{relation} uses unsupported kind {kind!r}."
                )
            result[relation] = {
                "field": field_name,
                "kind": lower_kind,
                **{
                    attr: value
                    for attr, value in binding.items()
                    if attr not in {"field", "kind"}
                },
            }
        return result

    @staticmethod
    def _extract_iterable(cfg: Mapping[str, object], key: str) -> Iterable[str]:
        value = cfg.get(key, ())
        if not value:
            return ()
        if not isinstance(value, Iterable):
            raise TypeGraphError(f"{key!r} must be iterable.")
        for entry in value:
            if not isinstance(entry, str):
                raise TypeGraphError(f"{key!r} entries must be strings.")
            yield entry

    def _validate_parents(self) -> None:
        for cfg in self._types.values():
            for parent in cfg.parents:
                if parent not in self._types:
                    raise UnknownParentError(
                        f"type {cfg.name!r} references unknown parent {parent!r}"
                    )

    def _validate_parent_cycles(self) -> None:
        visited: Set[str] = set()
        stack: Set[str] = set()

        def dfs(node: str) -> None:
            if node in stack:
                raise TypeGraphError(f"parent cycle detected at type {node!r}")
            if node in visited:
                return
            stack.add(node)
            for parent in self._types[node].parents:
                dfs(parent)
            stack.remove(node)
            visited.add(node)

        for name in self._types:
            if name not in visited:
                dfs(name)

    def _validate_relation_subjects(self) -> None:
        known_types = set(self._types.keys())
        for cfg in self._types.values():
            for relation, subject in cfg.relations.items():
                subject_type = subject.split("#", maxsplit=1)[0]
                if subject_type not in known_types:
                    raise UnknownRelationSubject(
                        f"relation {cfg.name}.{relation} points to unknown type "
                        f"{subject_type!r}"
                    )

    def _validate_permission_expressions(self) -> None:
        for cfg in self._types.values():
            known_tokens = set(cfg.relations) | set(cfg.permissions)
            for perm, expression in cfg.permissions.items():
                for token in self._tokenize_expression(expression):
                    if token in {"|", "&", "(", ")", "!"}:
                        continue
                    if token not in known_tokens:
                        raise InvalidPermissionExpression(
                            f"permission {cfg.name}.{perm} references unknown token "
                            f"{token!r}"
                        )

    def _validate_bindings(self) -> None:
        for cfg in self._types.values():
            if not cfg.bindings:
                continue
            for relation_name in cfg.bindings.keys():
                if relation_name not in cfg.relations:
                    raise TypeGraphError(
                        f"binding for {cfg.name}.{relation_name} "
                        "must target a defined relation."
                    )

    @staticmethod
    def _tokenize_expression(expression: str) -> Iterable[str]:
        without_arrow = _PERMISSION_ARROW.sub(" ", expression)
        cleaned = _PERMISSION_TOKEN_DELIMS.sub(" ", without_arrow)
        for candidate in cleaned.split():
            yield candidate.strip()
