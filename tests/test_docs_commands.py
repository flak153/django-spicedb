"""Guard against docs referencing management commands that don't exist."""

import re
from pathlib import Path

import pytest

# Commands shipped under django_spicedb/management/commands/
COMMANDS_DIR = Path(__file__).resolve().parent.parent / "django_spicedb" / "management" / "commands"

# Docs that reference `manage.py <command>`
DOC_FILES = [
    Path(__file__).resolve().parent.parent / "README.md",
    Path(__file__).resolve().parent.parent / "docs" / "tutorial.md",
    Path(__file__).resolve().parent.parent / "developers.md",
]

# Pattern: "manage.py <command_name>" (captures command_name)
MANAGE_PY_RE = re.compile(r"manage\.py\s+([a-z_]+)")


def _get_shipped_commands() -> set[str]:
    """Return the set of command names that actually exist on disk."""
    return {
        p.stem
        for p in COMMANDS_DIR.glob("*.py")
        if p.stem != "__init__"
    }


def _get_referenced_commands(path: Path) -> set[str]:
    """Return command names referenced via manage.py in a doc file."""
    if not path.exists():
        return set()
    text = path.read_text()
    return set(MANAGE_PY_RE.findall(text))


# Built-in Django commands that are fine to reference
DJANGO_BUILTINS = {
    "migrate", "makemigrations", "runserver", "createsuperuser",
    "shell", "test", "collectstatic", "startapp", "startproject",
    "check", "showmigrations", "flush", "dbshell", "diffsettings",
    "inspectdb", "loaddata", "dumpdata", "sendtestemail",
    "changepassword", "clearsessions", "squashmigrations",
}


@pytest.mark.parametrize("doc_file", DOC_FILES, ids=lambda p: p.name)
def test_docs_reference_only_existing_commands(doc_file):
    """Every manage.py command referenced in docs must exist on disk."""
    shipped = _get_shipped_commands()
    referenced = _get_referenced_commands(doc_file)

    # Filter out Django builtins
    project_commands = referenced - DJANGO_BUILTINS

    missing = project_commands - shipped
    assert not missing, (
        f"{doc_file.name} references commands that don't exist: {missing}\n"
        f"Shipped commands: {sorted(shipped)}"
    )
