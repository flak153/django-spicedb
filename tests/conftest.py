import os
import subprocess
import time
from collections.abc import Iterator

import grpc
import pytest

from django_rebac.adapters.spicedb import SpiceDBAdapter

SPICEDB_ENDPOINT = os.getenv("SPICEDB_ENDPOINT", "localhost:50051")
SPICEDB_TOKEN = os.getenv("SPICEDB_PRESHARED_KEY", "devkey")

_STACK_READY = False
_STACK_ERROR: str | None = None


def _ensure_stack() -> None:
    global _STACK_READY, _STACK_ERROR
    if _STACK_READY:
        return
    if _STACK_ERROR:
        raise RuntimeError(_STACK_ERROR)
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "spicedb-db"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker",
                "compose",
                "run",
                "--rm",
                "spicedb",
                "migrate",
                "head",
                "--datastore-engine",
                "postgres",
                "--datastore-conn-uri",
                "postgres://spicedb:spicedb@spicedb-db:5432/spicedb?sslmode=disable",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["docker", "compose", "up", "-d", "spicedb"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - environment specific
        _STACK_ERROR = exc.stderr.decode() if exc.stderr else str(exc)
        raise RuntimeError(_STACK_ERROR) from exc

    _wait_for_grpc(SPICEDB_ENDPOINT)
    _STACK_READY = True


def _wait_for_grpc(endpoint: str, timeout: float = 30.0) -> None:
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
    raise RuntimeError(f"SpiceDB at {endpoint} did not become ready in time.")


@pytest.fixture
def spicedb_adapter() -> Iterator[SpiceDBAdapter]:
    try:
        _ensure_stack()
    except RuntimeError as exc:
        pytest.skip(f"SpiceDB stack unavailable: {exc}")

    adapter = SpiceDBAdapter(endpoint=SPICEDB_ENDPOINT, token=SPICEDB_TOKEN, insecure=True)
    try:
        yield adapter
    finally:
        adapter.close()
