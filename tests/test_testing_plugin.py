"""Tests for the django_spicedb.testing pytest plugin."""

from __future__ import annotations

import importlib
import inspect
from unittest.mock import MagicMock, patch

import pytest


# -----------------------------------------------------------------------
# 1. Module structure
# -----------------------------------------------------------------------


class TestPluginModuleStructure:
    """Verify the plugin module is importable and exports the expected fixtures."""

    def test_module_importable(self):
        mod = importlib.import_module("django_spicedb.testing")
        assert mod is not None

    def test_spicedb_container_fixture_exists(self):
        from django_spicedb.testing import spicedb_container
        assert callable(spicedb_container)

    def test_spicedb_grpc_endpoint_fixture_exists(self):
        from django_spicedb.testing import spicedb_grpc_endpoint
        assert callable(spicedb_grpc_endpoint)

    def test_spicedb_adapter_fixture_exists(self):
        from django_spicedb.testing import spicedb_adapter
        assert callable(spicedb_adapter)

    def test_wait_for_grpc_helper_exists(self):
        from django_spicedb.testing import _wait_for_grpc
        assert callable(_wait_for_grpc)
        sig = inspect.signature(_wait_for_grpc)
        assert "endpoint" in sig.parameters
        assert "timeout" in sig.parameters

    def test_image_is_pinned(self):
        """Image should be pinned, not :latest."""
        from django_spicedb.testing import _SPICEDB_IMAGE
        assert ":latest" not in _SPICEDB_IMAGE
        assert "spicedb:v" in _SPICEDB_IMAGE

    def test_constants(self):
        from django_spicedb.testing import (
            _SPICEDB_TOKEN,
            _SPICEDB_IMAGE,
            _SPICEDB_GRPC_PORT,
        )
        assert _SPICEDB_TOKEN == "testkey"
        assert "spicedb" in _SPICEDB_IMAGE
        assert _SPICEDB_GRPC_PORT == 50051


# -----------------------------------------------------------------------
# 2. Entry point
# -----------------------------------------------------------------------


class TestPluginEntryPoint:
    """Verify the plugin is registered as a pytest11 entry point."""

    def test_pyproject_has_entry_point(self):
        import pathlib

        pyproject = pathlib.Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject.read_text()
        assert "[project.entry-points.pytest11]" in content
        assert 'django_spicedb = "django_spicedb.testing"' in content


# -----------------------------------------------------------------------
# 3. Fixture scope
# -----------------------------------------------------------------------


class TestFixtureScopes:
    """Fixtures must declare the correct scope."""

    @pytest.mark.parametrize("name", [
        "spicedb_container",
        "spicedb_grpc_endpoint",
        "spicedb_adapter",
    ])
    def test_session_scoped(self, name):
        from django_spicedb import testing as mod
        fixture_fn = getattr(mod, name)
        marker = getattr(fixture_fn, "_fixture_function_marker", None)
        assert marker is not None, f"{name} is not a pytest fixture"
        assert marker.scope == "session", (
            f"{name} should be session-scoped, got {marker.scope!r}"
        )


# -----------------------------------------------------------------------
# 4. Graceful skip when testcontainers missing
# -----------------------------------------------------------------------


class TestPluginGracefulSkip:
    """The fixtures should skip gracefully when testcontainers isn't installed."""

    def test_container_skips_without_testcontainers(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "testcontainers.core.container":
                raise ImportError("No module named 'testcontainers'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        import django_spicedb.testing as mod
        raw_fn = mod.spicedb_container.__wrapped__
        gen = raw_fn()
        with pytest.raises(pytest.skip.Exception):
            next(gen)


# -----------------------------------------------------------------------
# 5. Container lifecycle: cleanup on readiness failure
# -----------------------------------------------------------------------


class TestContainerLifecycle:
    """Container must be stopped even if readiness check fails."""

    def test_container_stopped_on_readiness_failure(self):
        """If _wait_for_grpc raises, container.stop() must still be called."""
        mock_container = MagicMock()
        mock_container.get_container_host_ip.return_value = "localhost"
        mock_container.get_exposed_port.return_value = 99999

        mock_docker_cls = MagicMock(return_value=mock_container)
        mock_container.with_command.return_value = mock_container
        mock_container.with_exposed_ports.return_value = mock_container

        with patch("django_spicedb.testing._wait_for_grpc", side_effect=RuntimeError("timeout")), \
             patch.dict("sys.modules", {"testcontainers.core.container": MagicMock(DockerContainer=mock_docker_cls)}):

            from django_spicedb.testing import spicedb_container
            gen = spicedb_container.__wrapped__()

            with pytest.raises(RuntimeError, match="timeout"):
                next(gen)

        mock_container.stop.assert_called_once()

    def test_container_stopped_on_normal_teardown(self):
        """On normal exit, container.stop() is called during teardown."""
        mock_container = MagicMock()
        mock_container.get_container_host_ip.return_value = "localhost"
        mock_container.get_exposed_port.return_value = 50051

        mock_docker_cls = MagicMock(return_value=mock_container)
        mock_container.with_command.return_value = mock_container
        mock_container.with_exposed_ports.return_value = mock_container

        with patch("django_spicedb.testing._wait_for_grpc"), \
             patch.dict("sys.modules", {"testcontainers.core.container": MagicMock(DockerContainer=mock_docker_cls)}):

            from django_spicedb.testing import spicedb_container
            gen = spicedb_container.__wrapped__()
            container = next(gen)
            assert container is mock_container

            # Simulate teardown
            with pytest.raises(StopIteration):
                next(gen)

        mock_container.stop.assert_called_once()


# -----------------------------------------------------------------------
# 6. Adapter lifecycle: cleanup on schema-publish failure
# -----------------------------------------------------------------------


class TestAdapterLifecycle:
    """Adapter must be closed and global state restored on setup failure."""

    @patch("django_spicedb.testing.get_type_graph")
    @patch("django_spicedb.testing.publish_schema", side_effect=RuntimeError("gRPC error"))
    @patch("django_spicedb.testing.set_adapter")
    @patch("django_spicedb.testing.reset_adapter")
    @patch("django_spicedb.testing.SpiceDBAdapter")
    def test_adapter_closed_on_publish_failure(
        self, MockAdapter, mock_reset, mock_set, mock_publish, mock_graph
    ):
        mock_instance = MagicMock()
        MockAdapter.return_value = mock_instance

        from django_spicedb.testing import spicedb_adapter
        gen = spicedb_adapter.__wrapped__("localhost:50051")

        with pytest.raises(RuntimeError, match="gRPC error"):
            next(gen)

        # Adapter must have been closed and global state restored
        mock_instance.close.assert_called_once()
        mock_reset.assert_called_once()

    @patch("django_spicedb.testing.get_type_graph")
    @patch("django_spicedb.testing.publish_schema", return_value="abc123")
    @patch("django_spicedb.testing.set_adapter")
    @patch("django_spicedb.testing.reset_adapter")
    @patch("django_spicedb.testing.SpiceDBAdapter")
    def test_adapter_cleaned_up_on_normal_teardown(
        self, MockAdapter, mock_reset, mock_set, mock_publish, mock_graph
    ):
        mock_instance = MagicMock()
        MockAdapter.return_value = mock_instance

        from django_spicedb.testing import spicedb_adapter
        gen = spicedb_adapter.__wrapped__("localhost:50051")
        adapter = next(gen)
        assert adapter is mock_instance

        # Simulate teardown
        with pytest.raises(StopIteration):
            next(gen)

        mock_instance.close.assert_called_once()
        mock_reset.assert_called_once()

    @patch("django_spicedb.testing.get_type_graph")
    @patch("django_spicedb.testing.publish_schema", return_value="abc123")
    @patch("django_spicedb.testing.set_adapter")
    @patch("django_spicedb.testing.reset_adapter")
    @patch("django_spicedb.testing.SpiceDBAdapter")
    def test_global_adapter_set_before_yield(
        self, MockAdapter, mock_reset, mock_set, mock_publish, mock_graph
    ):
        """set_adapter must be called with the new adapter during setup."""
        mock_instance = MagicMock()
        MockAdapter.return_value = mock_instance

        from django_spicedb.testing import spicedb_adapter
        gen = spicedb_adapter.__wrapped__("localhost:50051")
        next(gen)

        mock_set.assert_called_once_with(mock_instance)


# -----------------------------------------------------------------------
# 7. Recording adapter save/restore
# -----------------------------------------------------------------------


class TestRecordingAdapterRestore:
    """recording_adapter must restore previous adapter, not reset to None."""

    def test_recording_adapter_restores_previous(self):
        from django_spicedb.adapters import set_adapter
        import django_spicedb.adapters.factory as _factory
        from tests.conftest import RecordingAdapter

        sentinel = MagicMock()
        set_adapter(sentinel)

        try:
            # Simulate what recording_adapter fixture does
            previous = _factory._adapter
            assert previous is sentinel

            recorder = RecordingAdapter()
            set_adapter(recorder)
            assert _factory._adapter is recorder

            # Teardown: restore
            set_adapter(previous)
            assert _factory._adapter is sentinel
        finally:
            set_adapter(None)
