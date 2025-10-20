"""Minimal TypeGraph implementation used in early tests.

The goal is not to be feature complete but to provide a concrete object that
can validate a toy configuration and render a tiny SpiceDB-like schema string.
This gives us something executable for unit tests while the broader design in
``planning.md`` evolves into fuller modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, MutableMapping


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


class TypeGraph:
    """Registry of ``TypeConfig`` objects with lightweight validation."""

    def __init__(self, types: Mapping[str, Mapping[str, object]] | None = None) -> None:
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
            )
        self._validate_parents()
        self._validate_relation_subjects()
        self._validate_permission_expressions()

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

    @staticmethod
    def _tokenize_expression(expression: str) -> Iterable[str]:
        token = []
        for char in expression:
            if char.isalnum() or char in {"_", "-", ">"}:
                token.append(char)
                continue
            if token:
                yield "".join(token)
                token.clear()
            if not char.isspace():
                yield char
        if token:
            yield "".join(token)
