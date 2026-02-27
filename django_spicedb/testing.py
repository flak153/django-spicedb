"""Pytest plugin: ephemeral SpiceDB via testcontainers.

Registered as a ``pytest11`` entry point so downstream projects get
these fixtures automatically after ``pip install django-spicedb[test]``.

Fixtures
--------
``spicedb_container`` (session)
    Starts an in-memory SpiceDB container using ``serve-testing``.
``spicedb_grpc_endpoint`` (session)
    Returns the ``host:port`` string for the container's gRPC server.
``spicedb_adapter`` (session)
    A :class:`~django_spicedb.adapters.spicedb.SpiceDBAdapter` wired to
    the container.  Overrides the global adapter and publishes the
    current ReBAC schema on creation.
"""

from __future__ import annotations

import time

import pytest

from django_spicedb.adapters.spicedb import SpiceDBAdapter
from django_spicedb.adapters import set_adapter, reset_adapter
from django_spicedb.schema import publish_schema
from django_spicedb.conf import get_type_graph

_SPICEDB_TOKEN = "testkey"
_SPICEDB_IMAGE = "authzed/spicedb:v1.36.0"
_SPICEDB_GRPC_PORT = 50051


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="session")
def spicedb_container():
    """Start an ephemeral in-memory SpiceDB container for the test session.

    Requires ``testcontainers``.  Install with::

        pip install django-spicedb[test]

    The container runs SpiceDB ``serve-testing`` — an in-memory datastore
    with no external dependencies.
    """
    try:
        from testcontainers.core.container import DockerContainer
    except ImportError:
        pytest.skip(
            "testcontainers is required for SpiceDB test containers. "
            "Install with: pip install django-spicedb[test]"
        )

    container = (
        DockerContainer(_SPICEDB_IMAGE)
        .with_command(f"serve-testing --grpc-preshared-key {_SPICEDB_TOKEN}")
        .with_exposed_ports(_SPICEDB_GRPC_PORT)
    )
    container.start()

    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(_SPICEDB_GRPC_PORT)
        _wait_for_grpc(f"{host}:{port}")
    except Exception:
        container.stop()
        raise

    yield container

    container.stop()


@pytest.fixture(scope="session")
def spicedb_grpc_endpoint(spicedb_container) -> str:
    """Return the ``host:port`` of the test SpiceDB gRPC server."""
    host = spicedb_container.get_container_host_ip()
    port = spicedb_container.get_exposed_port(_SPICEDB_GRPC_PORT)
    return f"{host}:{port}"


@pytest.fixture(scope="session")
def spicedb_adapter(spicedb_grpc_endpoint):
    """Session-scoped :class:`SpiceDBAdapter` wired to the test container.

    * Overrides the global adapter so all ``django-spicedb`` code uses it.
    * Publishes the current ReBAC schema on first use.
    """
    adapter = SpiceDBAdapter(
        endpoint=spicedb_grpc_endpoint,
        token=_SPICEDB_TOKEN,
        insecure=True,
    )

    try:
        set_adapter(adapter)
        graph = get_type_graph()
        publish_schema(adapter, graph=graph)
    except Exception:
        adapter.close()
        reset_adapter()
        raise

    yield adapter

    adapter.close()
    reset_adapter()


# ------------------------------------------------------------------ helpers


def _wait_for_grpc(endpoint: str, timeout: float = 30.0) -> None:
    """Block until the gRPC server at *endpoint* is ready."""
    import grpc

    channel = grpc.insecure_channel(endpoint)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            grpc.channel_ready_future(channel).result(timeout=1.0)
            channel.close()
            return
        except grpc.FutureTimeoutError:
            time.sleep(0.5)
    channel.close()
    raise RuntimeError(f"SpiceDB at {endpoint} did not become ready within {timeout}s")
