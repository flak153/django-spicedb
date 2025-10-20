"""SpiceDB gRPC adapter implementation."""

from __future__ import annotations

import grpc
from typing import Iterable, Sequence

from authzed.api.v1 import (
    core_pb2 as core_pb,
    permission_service_pb2 as perm_pb,
    permission_service_pb2_grpc as perm_grpc,
    schema_service_pb2 as schema_pb,
    schema_service_pb2_grpc as schema_grpc,
)

from .base import RebacAdapter, TupleKey, TupleWrite


class SpiceDBAdapter(RebacAdapter):
    """Adapter that talks to SpiceDB over gRPC."""

    def __init__(
        self,
        *,
        endpoint: str,
        token: str,
        insecure: bool = True,
        grpc_options: Sequence[tuple[str, str]] = (),
    ) -> None:
        if insecure:
            self._channel = grpc.insecure_channel(endpoint, options=grpc_options)
        else:
            self._channel = grpc.secure_channel(
                endpoint,
                grpc.ssl_channel_credentials(),
                options=grpc_options,
            )

        self._metadata = (("authorization", f"Bearer {token}"),)
        self._schema_client = schema_grpc.SchemaServiceStub(self._channel)
        self._permission_client = perm_grpc.PermissionsServiceStub(self._channel)

    # ------------------------------------------------------------------ schema
    def publish_schema(self, schema: str) -> str:
        response = self._schema_client.WriteSchema(
            schema_pb.WriteSchemaRequest(schema=schema),
            metadata=self._metadata,
        )
        return response.written_at.token

    # ---------------------------------------------------------------- tuples --
    def write_tuples(self, tuples: Sequence[TupleWrite]) -> None:
        updates = [
            self._build_update(tuple_write, core_pb.RelationshipUpdate.Operation.OPERATION_TOUCH)
            for tuple_write in tuples
        ]
        if not updates:
            return
        self._permission_client.WriteRelationships(
            perm_pb.WriteRelationshipsRequest(updates=updates),
            metadata=self._metadata,
        )

    def delete_tuples(self, tuples: Sequence[TupleKey]) -> None:
        for key in tuples:
            resource_type, resource_id = _parse_object(key.object)
            subject_type, subject_id, subject_relation = _parse_subject(key.subject)

            subject_filter = perm_pb.SubjectFilter(
                subject_type=subject_type,
                optional_subject_id=subject_id,
            )
            if subject_relation:
                subject_filter.optional_relation.relation = subject_relation

            request = perm_pb.DeleteRelationshipsRequest(
                relationship_filter=perm_pb.RelationshipFilter(
                    resource_type=resource_type,
                    optional_resource_id=resource_id,
                    optional_relation=key.relation,
                    optional_subject_filter=subject_filter,
                )
            )
            self._permission_client.DeleteRelationships(
                request,
                metadata=self._metadata,
            )

    # -------------------------------------------------------------- permission
    def check(
        self,
        subject: str,
        relation: str,
        object_: str,
        *,
        context: dict | None = None,
        consistency: str | None = None,
    ) -> bool:
        resource_type, resource_id = _parse_object(object_)
        subject_ref = _build_subject(subject)

        request = perm_pb.CheckPermissionRequest(
            resource=_build_object(resource_type, resource_id),
            permission=relation,
            subject=subject_ref,
        )

        if context:
            request.context = perm_pb.Context()
            request.context.fields.update(context)

        if consistency:
            request.consistency.CopyFrom(_consistency(consistency))

        response = self._permission_client.CheckPermission(
            request,
            metadata=self._metadata,
        )
        return response.permissionship == perm_pb.CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION

    def lookup_resources(
        self,
        subject: str,
        relation: str,
        resource_type: str,
        *,
        context: dict | None = None,
        consistency: str | None = None,
    ) -> Iterable[str]:
        request = perm_pb.LookupResourcesRequest(
            resource_object_type=resource_type,
            permission=relation,
            subject=_build_subject(subject),
        )
        if context:
            request.context = perm_pb.Context()
            request.context.fields.update(context)
        if consistency:
            request.consistency.CopyFrom(_consistency(consistency))

        stream = self._permission_client.LookupResources(
            request,
            metadata=self._metadata,
        )
        for item in stream:
            yield item.resource_object_id

    # ---------------------------------------------------------------- cleanup -
    def close(self) -> None:
        self._channel.close()

    # ---------------------------------------------------------------- helpers -
    def _build_update(self, tuple_write: TupleWrite, operation: int) -> core_pb.RelationshipUpdate:
        resource_type, resource_id = _parse_object(tuple_write.key.object)
        relationship = core_pb.Relationship(
            resource=_build_object(resource_type, resource_id),
            relation=tuple_write.key.relation,
            subject=_build_subject(tuple_write.key.subject),
        )

        if tuple_write.condition:
            name = tuple_write.condition.get("name")
            if not name:
                raise ValueError("tuple condition requires 'name'")
            context = tuple_write.condition.get("context", {}) or {}
            caveat = core_pb.ContextualizedCaveat(caveat_name=name)
            if context:
                caveat.context.update(context)  # type: ignore[arg-type]
            relationship.optional_caveat.CopyFrom(caveat)

        return core_pb.RelationshipUpdate(
            operation=operation,
            relationship=relationship,
        )


def _parse_object(value: str) -> tuple[str, str]:
    try:
        object_type, object_id = value.split(":", 1)
    except ValueError as exc:  # pragma: no cover
        raise ValueError(f"Invalid object reference {value!r}") from exc
    return object_type, object_id


def _parse_subject(value: str) -> tuple[str, str, str]:
    if "#" in value:
        object_part, relation = value.split("#", 1)
    else:
        object_part, relation = value, ""
    object_type, object_id = _parse_object(object_part)
    return object_type, object_id, relation


def _build_object(object_type: str, object_id: str) -> core_pb.ObjectReference:
    return core_pb.ObjectReference(object_type=object_type, object_id=object_id)


def _build_subject(value: str) -> core_pb.SubjectReference:
    subject_type, subject_id, relation = _parse_subject(value)
    subject_ref = core_pb.SubjectReference(object=_build_object(subject_type, subject_id))
    if relation:
        subject_ref.optional_relation = relation
    return subject_ref


def _consistency(mode: str) -> perm_pb.Consistency:
    consistency = perm_pb.Consistency()
    if mode == "fully_consistent":
        consistency.fully_consistent = True
    elif mode == "minimize_latency":
        consistency.minimize_latency = True
    else:
        consistency.at_least_as_fresh.token = mode
    return consistency
