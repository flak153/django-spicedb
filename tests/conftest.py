import os
import subprocess
import time
from collections.abc import Iterator
from typing import Any, Mapping

import grpc
import pytest

from django_rebac.adapters import reset_adapter, set_adapter
from django_rebac.adapters.base import TupleKey, TupleWrite
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


class RecordingAdapter:
    def __init__(self) -> None:
        self.schema: str | None = None
        self.zedtokens: list[str] = []
        self.writes: list[TupleWrite] = []
        self.deletes: list[TupleKey] = []
        self._check_responses: dict[tuple, bool] = {}
        self._lookup_responses: dict[tuple, list[str]] = {}
        self.check_calls: list[tuple] = []
        self.lookup_calls: list[tuple] = []

    def publish_schema(self, schema: str) -> str:
        self.schema = schema
        token = f"token-{len(self.zedtokens) + 1}"
        self.zedtokens.append(token)
        return token

    def write_tuples(self, tuples):
        self.writes.extend(tuples)

    def delete_tuples(self, tuples):
        self.deletes.extend(tuples)

    def set_check_response(
        self,
        *,
        subject: str,
        relation: str,
        object_ref: str,
        result: bool,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> None:
        key = (subject, relation, object_ref, consistency, tuple(sorted((context or {}).items())))
        self._check_responses[key] = result

    def check(
        self,
        subject: str,
        relation: str,
        object_: str,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> bool:
        key = (subject, relation, object_, consistency, tuple(sorted((context or {}).items())))
        self.check_calls.append(key)
        return self._check_responses.get(key, False)

    def set_lookup_response(
        self,
        *,
        subject: str,
        relation: str,
        resource_type: str,
        results: list[str],
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ) -> None:
        key = (subject, relation, resource_type, consistency, tuple(sorted((context or {}).items())))
        self._lookup_responses[key] = results

    def lookup_resources(
        self,
        subject: str,
        relation: str,
        resource_type: str,
        *,
        context: Mapping[str, Any] | None = None,
        consistency: str | None = None,
    ):
        key = (subject, relation, resource_type, consistency, tuple(sorted((context or {}).items())))
        self.lookup_calls.append(key)
        return iter(self._lookup_responses.get(key, []))


@pytest.fixture
def recording_adapter() -> Iterator[RecordingAdapter]:
    adapter = RecordingAdapter()
    set_adapter(adapter)
    yield adapter
    reset_adapter()
