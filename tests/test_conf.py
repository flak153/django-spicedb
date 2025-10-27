import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.models import TypeDefinition
from django_rebac.types import TypeGraph


@pytest.fixture(autouse=True)
def reset_graph_cache():
    conf.reset_type_graph_cache()
    yield
    conf.reset_type_graph_cache()


@override_settings(
    REBAC={
        "types": {
            "user": {"model": "django.contrib.auth.models.User"},
            "doc": {"model": "example_project.documents.models.Document"},
        }
    }
)
def test_get_type_graph_builds_from_settings() -> None:
    graph = conf.get_type_graph()

    assert isinstance(graph, TypeGraph)
    assert "user" in graph.types
    assert "doc" in graph.types


@override_settings(REBAC=None)
def test_missing_rebac_settings_raises() -> None:
    with pytest.raises(ImproperlyConfigured):
        conf.get_type_graph()


@override_settings(REBAC={"types": {"user": {"model": "django.contrib.auth.models.User"}}})
def test_cache_reused_between_calls() -> None:
    first = conf.get_type_graph()
    second = conf.get_type_graph()

    assert first is second


@pytest.mark.django_db
@override_settings(REBAC={"types": {"user": {"model": "django.contrib.auth.models.User"}}, "db_overrides": False})
def test_db_overrides_disabled() -> None:
    TypeDefinition.objects.create(
        name="document",
        model="example_project.documents.models.Document",
        relations={"owner": "user"},
    )

    graph = conf.get_type_graph()

    assert "document" not in graph.types


@pytest.mark.django_db
@override_settings(REBAC={"types": {"user": {"model": "django.contrib.auth.models.User"}}, "db_overrides": True})
def test_db_overrides_enabled() -> None:
    TypeDefinition.objects.create(
        name="document",
        model="example_project.documents.models.Document",
        relations={"owner": "user"},
        permissions={"view": "owner"},
        parents=[],
        bindings={"owner": {"field": "owner", "kind": "fk"}},
    )

    graph = conf.get_type_graph()

    assert "document" in graph.types
    document = graph.types["document"]
    assert document.relations["owner"] == "user"
    assert document.permissions["view"] == "owner"
