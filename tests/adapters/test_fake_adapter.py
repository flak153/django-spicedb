from django_rebac.adapters.base import TupleKey, TupleWrite
from django_rebac.adapters.fake import FakeAdapter


def test_fake_adapter_tracks_schema_and_tuples() -> None:
    adapter = FakeAdapter()

    token = adapter.publish_schema("schema text")

    assert adapter.published_schemas[-1] == "schema text"
    assert token.startswith("fake-schema-")

    write = TupleWrite(key=TupleKey(object="document:1", relation="owner", subject="user:1"))
    adapter.write_tuples([write])
    adapter.delete_tuples([write.key])

    assert adapter.written_tuples == [write]
    assert adapter.deleted_tuples == [write.key]
