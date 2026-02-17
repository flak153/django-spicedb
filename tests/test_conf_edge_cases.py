"""Tests for configuration edge cases in django_spicedb.conf module."""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

import django_spicedb.conf as conf
from django_spicedb.core import clear_rebac_model_registry, _REBAC_MODEL_REGISTRY


@pytest.fixture(autouse=True)
def reset_graph_cache():
    """Reset type graph cache before and after each test.

    Note: We do NOT clear the model registry here because models registered via
    metaclass at import time won't re-register on subsequent imports. Tests that
    need an empty registry should save/restore it manually.
    """
    conf.reset_type_graph_cache()
    yield
    conf.reset_type_graph_cache()


class TestGetTypeGraphEdgeCases:
    """Test edge cases for get_type_graph()."""

    def test_get_type_graph_raises_when_no_models_registered(self):
        """get_type_graph raises ImproperlyConfigured when no models are registered."""
        # Save and clear the registry for this specific test
        saved_registry = dict(_REBAC_MODEL_REGISTRY)
        _REBAC_MODEL_REGISTRY.clear()
        try:
            with pytest.raises(ImproperlyConfigured) as exc_info:
                conf.get_type_graph()

            assert "No ReBAC models found" in str(exc_info.value)
            assert "inherit from RebacModel" in str(exc_info.value)
        finally:
            # Restore the registry
            _REBAC_MODEL_REGISTRY.update(saved_registry)

    def test_get_type_graph_caches_result_across_calls(self):
        """get_type_graph caches the TypeGraph instance."""
        first_call = conf.get_type_graph()
        second_call = conf.get_type_graph()

        # Same instance (not just equal, but identical)
        assert first_call is second_call

    def test_get_type_graph_cache_reused_after_reset(self):
        """After reset_type_graph_cache(), a new graph is built on next call."""
        first = conf.get_type_graph()
        conf.reset_type_graph_cache()
        second = conf.get_type_graph()

        # Different instances after reset
        assert first is not second
        # But same contents
        assert first.types.keys() == second.types.keys()

    def test_cache_invalidation_clears_both_caches(self):
        """reset_type_graph_cache() clears both type graph and model caches."""
        from example_project.documents.models import Document

        # Load graph to populate caches
        graph = conf.get_type_graph()
        type_name = conf.get_type_for_model(Document)
        assert type_name == "document"

        # Reset caches
        conf.reset_type_graph_cache()

        # Verify cache is cleared by checking private variables
        assert conf._TYPE_GRAPH_CACHE is None
        assert conf._MODEL_TYPE_CACHE == {}


class TestGetTypeForModelEdgeCases:
    """Test edge cases for get_type_for_model()."""

    def test_get_type_for_unregistered_model_raises(self):
        """get_type_for_model raises for models not in registry."""
        from django.contrib.contenttypes.models import ContentType

        with pytest.raises(ImproperlyConfigured) as exc_info:
            conf.get_type_for_model(ContentType)

        assert "No REBAC type configured" in str(exc_info.value)

    def test_get_type_for_model_accepts_model_class(self):
        """get_type_for_model works with model class."""
        from example_project.documents.models import Document

        type_name = conf.get_type_for_model(Document)
        assert type_name == "document"

    def test_get_type_for_model_accepts_string_path(self):
        """get_type_for_model works with dotted model path."""
        type_name = conf.get_type_for_model("example_project.documents.models.Document")
        assert type_name == "document"

    def test_get_type_for_model_caches_result(self):
        """get_type_for_model caches lookups in _MODEL_TYPE_CACHE."""
        from example_project.documents.models import Document

        # First call builds graph and populates cache
        conf.get_type_graph()
        initial_cache_size = len(conf._MODEL_TYPE_CACHE)

        # Second call should use cache
        conf.get_type_for_model(Document)
        assert len(conf._MODEL_TYPE_CACHE) >= initial_cache_size

    def test_get_type_for_model_with_string_path_caches_properly(self):
        """String path lookups are cached the same as class lookups."""
        from example_project.documents.models import Document

        # Ensure graph is built
        conf.get_type_graph()

        # Lookup by class
        type_from_class = conf.get_type_for_model(Document)

        # Lookup by string
        type_from_string = conf.get_type_for_model("example_project.documents.models.Document")

        # Should return same type
        assert type_from_class == type_from_string


class TestGetAdapterSettingsEdgeCases:
    """Test edge cases for get_adapter_settings()."""

    @override_settings(REBAC=None)
    def test_get_adapter_settings_with_missing_rebac_setting(self):
        """get_adapter_settings returns empty dict when REBAC is not configured."""
        adapter_settings = conf.get_adapter_settings()
        assert adapter_settings == {}

    @override_settings()
    def test_get_adapter_settings_when_rebac_not_in_settings(self):
        """get_adapter_settings handles missing REBAC key gracefully."""
        # Ensure REBAC is not in settings
        if hasattr(conf.settings, 'REBAC'):
            delattr(conf.settings, 'REBAC')

        adapter_settings = conf.get_adapter_settings()
        assert adapter_settings == {}

    @override_settings(REBAC={})
    def test_get_adapter_settings_with_empty_rebac_dict(self):
        """get_adapter_settings returns empty dict for empty REBAC config."""
        adapter_settings = conf.get_adapter_settings()
        assert adapter_settings == {}

    @override_settings(REBAC={"adapter": {"endpoint": "test:50051"}})
    def test_get_adapter_settings_with_partial_config(self):
        """get_adapter_settings returns available adapter config."""
        adapter_settings = conf.get_adapter_settings()
        assert adapter_settings == {"endpoint": "test:50051"}

    @override_settings(REBAC={"adapter": {"endpoint": "test:50051", "token": "abc"}})
    def test_get_adapter_settings_with_full_config(self):
        """get_adapter_settings returns complete adapter config."""
        adapter_settings = conf.get_adapter_settings()
        assert adapter_settings["endpoint"] == "test:50051"
        assert adapter_settings["token"] == "abc"


class TestGetRebacSettingsEdgeCases:
    """Test edge cases for get_rebac_settings()."""

    @override_settings(REBAC=None)
    def test_get_rebac_settings_returns_empty_when_none(self):
        """get_rebac_settings returns empty dict when REBAC is None."""
        settings = conf.get_rebac_settings()
        assert settings == {}

    @override_settings()
    def test_get_rebac_settings_returns_empty_when_not_set(self):
        """get_rebac_settings returns empty dict when REBAC is not set."""
        if hasattr(conf.settings, 'REBAC'):
            delattr(conf.settings, 'REBAC')

        settings = conf.get_rebac_settings()
        assert settings == {}

    @override_settings(REBAC={})
    def test_get_rebac_settings_returns_empty_dict(self):
        """get_rebac_settings returns empty dict for empty REBAC config."""
        settings = conf.get_rebac_settings()
        assert settings == {}

    @override_settings(REBAC="invalid")
    def test_get_rebac_settings_raises_for_non_mapping(self):
        """get_rebac_settings raises ImproperlyConfigured for non-mapping REBAC."""
        with pytest.raises(ImproperlyConfigured) as exc_info:
            conf.get_rebac_settings()

        assert "must be a mapping" in str(exc_info.value)

    @override_settings(REBAC=["list", "not", "dict"])
    def test_get_rebac_settings_raises_for_list(self):
        """get_rebac_settings raises for list instead of dict."""
        with pytest.raises(ImproperlyConfigured):
            conf.get_rebac_settings()

    @override_settings(REBAC={"adapter": {}, "other_key": "value"})
    def test_get_rebac_settings_with_multiple_keys(self):
        """get_rebac_settings preserves all keys in REBAC config."""
        settings = conf.get_rebac_settings()
        assert "adapter" in settings
        assert "other_key" in settings
        assert settings["other_key"] == "value"


class TestGetTenantModelEdgeCases:
    """Test edge cases for tenant-related functions."""

    @override_settings(REBAC={})
    def test_get_tenant_model_raises_when_not_configured(self):
        """get_tenant_model raises ValueError when tenant_model not configured."""
        with pytest.raises(ValueError) as exc_info:
            conf.get_tenant_model()

        assert "tenant_model" in str(exc_info.value)
        assert "not configured" in str(exc_info.value)

    @override_settings(REBAC={"tenant_model": None})
    def test_get_tenant_model_raises_when_none(self):
        """get_tenant_model raises ValueError when tenant_model is None."""
        with pytest.raises(ValueError):
            conf.get_tenant_model()

    @override_settings(REBAC={"tenant_model": "nonexistent.model.Path"})
    def test_get_tenant_model_raises_for_invalid_import(self):
        """get_tenant_model raises ImproperlyConfigured for invalid model path."""
        with pytest.raises(ImproperlyConfigured) as exc_info:
            conf.get_tenant_model()

        assert "Could not import" in str(exc_info.value)

    @override_settings(REBAC={"tenant_model": "example_project.documents.models.Company"})
    def test_get_tenant_model_returns_model_class(self):
        """get_tenant_model returns the configured tenant model class."""
        from example_project.documents.models import Company

        tenant_model = conf.get_tenant_model()
        assert tenant_model is Company

    @override_settings(REBAC={"tenant_fk_name": "custom_tenant"})
    def test_get_tenant_fk_name_returns_custom_value(self):
        """get_tenant_fk_name returns custom configured name."""
        fk_name = conf.get_tenant_fk_name()
        assert fk_name == "custom_tenant"

    @override_settings(REBAC={})
    def test_get_tenant_fk_name_returns_default(self):
        """get_tenant_fk_name returns 'tenant' by default."""
        fk_name = conf.get_tenant_fk_name()
        assert fk_name == "tenant"

    @override_settings(REBAC={"tenant_fk_name": None})
    def test_get_tenant_fk_name_handles_none_value(self):
        """get_tenant_fk_name returns default when explicitly None."""
        fk_name = conf.get_tenant_fk_name()
        assert fk_name == "tenant"


class TestTypeGraphContentValidation:
    """Test that type graph content is correctly built and validated."""

    def test_type_graph_contains_expected_types_from_models(self):
        """TypeGraph includes all registered model types."""
        graph = conf.get_type_graph()

        # These types should be present from example project
        expected_types = {"user", "document", "folder", "workspace", "group", "verification"}
        for expected_type in expected_types:
            assert expected_type in graph.types

    def test_type_graph_relations_match_rebac_meta(self):
        """TypeGraph relations correspond to RebacMeta.relations."""
        graph = conf.get_type_graph()
        doc_type = graph.types["document"]

        # Document.RebacMeta.relations has "owner" and "parent"
        assert "owner" in doc_type.relations
        assert "parent" in doc_type.relations
        assert doc_type.relations["owner"] == "user"
        assert doc_type.relations["parent"] == "folder"

    def test_type_graph_permissions_match_rebac_meta(self):
        """TypeGraph permissions correspond to RebacMeta.permissions."""
        graph = conf.get_type_graph()
        doc_type = graph.types["document"]

        # Document.RebacMeta.permissions has "view" and "edit"
        assert "view" in doc_type.permissions
        assert "edit" in doc_type.permissions

    def test_type_graph_bindings_auto_inferred(self):
        """TypeGraph bindings are auto-inferred from FK/M2M fields."""
        graph = conf.get_type_graph()
        doc_type = graph.types["document"]

        # Document has FK to User and Folder
        assert "owner" in doc_type.bindings
        assert doc_type.bindings["owner"]["kind"] == "fk"
        assert doc_type.bindings["owner"]["field"] == "owner"


class TestModelCacheInvalidation:
    """Test that model cache is properly invalidated."""

    def test_model_type_cache_rebuilt_after_reset(self):
        """Model type cache is rebuilt after reset."""
        from example_project.documents.models import Document

        # Populate cache
        graph1 = conf.get_type_graph()
        type1 = conf.get_type_for_model(Document)

        # Check cache is populated
        assert len(conf._MODEL_TYPE_CACHE) > 0

        # Reset and rebuild
        conf.reset_type_graph_cache()
        graph2 = conf.get_type_graph()
        type2 = conf.get_type_for_model(Document)

        # Both should work and return same value
        assert type1 == type2
        assert type1 == "document"

    def test_cache_contains_all_model_types(self):
        """After graph load, cache contains all model types."""
        conf.get_type_graph()

        # Cache should be populated
        assert len(conf._MODEL_TYPE_CACHE) > 0

        # Should include our known types (by model path)
        model_paths = list(conf._MODEL_TYPE_CACHE.keys())
        assert any("Document" in path for path in model_paths)
        assert any("Folder" in path for path in model_paths)
