from django_rebac.adapters.base import TupleKey, TupleWrite
from django_rebac.adapters.fake import FakeAdapter
from django_rebac.sync.backfill import backfill_tuples


def test_backfill_batches_and_counts() -> None:
    adapter = FakeAdapter()
    tuples = [
        TupleWrite(key=TupleKey(object=f"doc:{i}", relation="owner", subject="user:1"))
        for i in range(3)
    ]

    count = backfill_tuples(adapter, tuples, batch_size=2)

    assert count == 3
    # Fake adapter stores writes in the order received
    assert adapter.written_tuples == tuples
