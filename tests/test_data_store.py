"""Unit tests for the data store module."""

import pytest

import data_store
from models import EmailRecord


@pytest.fixture(autouse=True)
def clean_store(app):
    """Clear the data store before and after each test (within app context)."""
    data_store.clear_records()
    yield
    data_store.clear_records()


def _make_record(**kwargs) -> EmailRecord:
    """Helper to create an EmailRecord with defaults."""
    defaults = {
        "sender": "test@example.com",
        "subject": "Test Subject",
    }
    defaults.update(kwargs)
    return EmailRecord(**defaults)


class TestAddRecord:
    """Test add_record functionality."""

    def test_add_record_returns_id(self):
        """add_record should return the record's ID string."""
        record = _make_record()
        result_id = data_store.add_record(record)
        assert result_id == record.id
        assert isinstance(result_id, str)
        assert len(result_id) > 0

    def test_add_multiple_records_returns_unique_ids(self):
        """Each added record should have a unique ID."""
        r1 = _make_record(sender="a@example.com")
        r2 = _make_record(sender="b@example.com")
        id1 = data_store.add_record(r1)
        id2 = data_store.add_record(r2)
        assert id1 != id2


class TestGetAllRecords:
    """Test get_all_records functionality."""

    def test_get_all_records_empty(self):
        """get_all_records should return empty list when store is empty."""
        records = data_store.get_all_records()
        assert records == []

    def test_get_all_records_returns_all_added(self):
        """get_all_records should return all records that were added."""
        r1 = _make_record(sender="a@example.com")
        r2 = _make_record(sender="b@example.com")
        r3 = _make_record(sender="c@example.com")
        data_store.add_record(r1)
        data_store.add_record(r2)
        data_store.add_record(r3)

        all_records = data_store.get_all_records()
        assert len(all_records) == 3
        senders = {r.sender for r in all_records}
        assert senders == {"a@example.com", "b@example.com", "c@example.com"}


class TestGetRecord:
    """Test get_record functionality."""

    def test_get_record_returns_correct_record(self):
        """get_record should return the record matching the given ID."""
        r1 = _make_record(sender="target@example.com")
        r2 = _make_record(sender="other@example.com")
        data_store.add_record(r1)
        data_store.add_record(r2)

        result = data_store.get_record(r1.id)
        assert result is not None
        assert result.id == r1.id
        assert result.sender == "target@example.com"

    def test_get_record_returns_none_for_unknown_id(self):
        """get_record should return None for an ID not in the store."""
        r1 = _make_record()
        data_store.add_record(r1)

        result = data_store.get_record("nonexistent-id-12345")
        assert result is None


class TestClearRecords:
    """Test clear_records functionality."""

    def test_clear_records_empties_the_store(self):
        """clear_records should remove all records from the store."""
        data_store.add_record(_make_record(sender="a@example.com"))
        data_store.add_record(_make_record(sender="b@example.com"))
        assert len(data_store.get_all_records()) == 2

        data_store.clear_records()
        assert data_store.get_all_records() == []

    def test_clear_records_on_empty_store(self):
        """clear_records should not error on an already empty store."""
        data_store.clear_records()
        assert data_store.get_all_records() == []
