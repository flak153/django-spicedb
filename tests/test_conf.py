"""Tests for django_rebac.conf module with model-centric configuration."""

import pytest
from django.test import override_settings

import django_rebac.conf as conf
from django_rebac.core import clear_rebac_model_registry, register_type
from django_rebac.types import TypeGraph


@pytest.fixture(autouse=True)
def reset_graph_cache():
    """Reset the type graph cache before and after each test."""
    conf.reset_type_graph_cache()
    yield
    conf.reset_type_graph_cache()


def test_get_type_graph_builds_from_model_registry() -> None:
    """TypeGraph is built from models with RebacMeta."""
    graph = conf.get_type_graph()

    assert isinstance(graph, TypeGraph)
    # These types come from models with RebacMeta
    assert "user" in graph.types
    assert "document" in graph.types
    assert "folder" in graph.types
    assert "hierarchy_node" in graph.types


def test_type_graph_contains_relations_from_rebac_meta() -> None:
    """Relations defined in RebacMeta are reflected in TypeGraph."""
    graph = conf.get_type_graph()

    document = graph.types["document"]
    assert "owner" in document.relations
    assert document.relations["owner"] == "user"
    assert "parent" in document.relations
    assert document.relations["parent"] == "folder"


def test_type_graph_contains_permissions_from_rebac_meta() -> None:
    """Permissions defined in RebacMeta are reflected in TypeGraph."""
    graph = conf.get_type_graph()

    document = graph.types["document"]
    assert "view" in document.permissions
    assert "edit" in document.permissions


def test_type_graph_auto_infers_bindings() -> None:
    """Bindings are auto-inferred from FK/M2M field types."""
    graph = conf.get_type_graph()

    document = graph.types["document"]
    # owner is FK -> fk binding
    assert "owner" in document.bindings
    assert document.bindings["owner"]["kind"] == "fk"

    workspace = graph.types["workspace"]
    # members is M2M -> m2m binding
    assert "member" in workspace.bindings
    assert workspace.bindings["member"]["kind"] == "m2m"


def test_cache_reused_between_calls() -> None:
    """TypeGraph is cached and reused between calls."""
    first = conf.get_type_graph()
    second = conf.get_type_graph()

    assert first is second


def test_get_type_for_model_returns_type_name() -> None:
    """get_type_for_model returns the correct type name."""
    from example_project.documents.models import Document

    type_name = conf.get_type_for_model(Document)
    assert type_name == "document"


def test_get_type_for_model_by_path() -> None:
    """get_type_for_model accepts a dotted model path."""
    type_name = conf.get_type_for_model("example_project.documents.models.Document")
    assert type_name == "document"


@override_settings(REBAC={"adapter": {"endpoint": "test:50051"}})
def test_get_adapter_settings() -> None:
    """get_adapter_settings returns adapter config from settings."""
    adapter_settings = conf.get_adapter_settings()
    assert adapter_settings["endpoint"] == "test:50051"


@override_settings(REBAC={})
def test_get_adapter_settings_empty() -> None:
    """get_adapter_settings returns empty dict if no adapter config."""
    adapter_settings = conf.get_adapter_settings()
    assert adapter_settings == {}
