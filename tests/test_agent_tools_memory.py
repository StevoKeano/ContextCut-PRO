"""
Tests for persistent memory agent tools: ``remember``, ``recall``, ``forget``.

Uses ``mock_sqlite`` fixture to avoid real database access.
"""

from unittest.mock import MagicMock

import pytest


def _make_row(data):
    """Create a MagicMock that responds to ``r['key']`` like sqlite3.Row."""
    row = MagicMock()
    row.__getitem__.side_effect = lambda k: data[k]
    row.__repr__ = lambda self: str(data)
    return row


class TestMemory:
    @pytest.fixture(autouse=True)
    def setup(self, mock_sqlite):
        self.mock_db = MagicMock()
        mock_sqlite.return_value = self.mock_db
        self.mock_cursor = MagicMock()
        self.mock_db.execute.return_value = self.mock_cursor
        self.mock_db.total_changes = 0

    def test_crud_cycle(self):
        from agent_handler import remember, recall, forget

        r1 = remember.invoke({"key": "user_name", "value": "Alice"})
        assert "Stored" in r1
        self.mock_db.execute.assert_called()

        self.mock_cursor.fetchall.return_value = [
            _make_row({"key": "user_name", "value": "Alice", "updated": "2025-01-01"})
        ]
        r2 = recall.invoke({"key": "user_name"})
        assert "Alice" in r2

        self.mock_db.total_changes = 1
        r3 = forget.invoke({"key": "user_name"})
        assert "Deleted" in r3

        self.mock_db.total_changes = 0
        self.mock_cursor.fetchall.return_value = []
        r4 = recall.invoke({"key": "user_name"})
        assert "No memory found" in r4

    def test_recall_empty_key_returns_all(self):
        from agent_handler import recall

        self.mock_cursor.fetchall.return_value = [
            _make_row({"key": "k1", "value": "v1", "updated": "2025-01-01"}),
            _make_row({"key": "k2", "value": "v2", "updated": "2025-01-02"}),
        ]
        result = recall.invoke({"key": ""})
        assert "k1" in result
        assert "k2" in result

    def test_recall_unknown_key(self):
        from agent_handler import recall

        self.mock_cursor.fetchall.return_value = []
        result = recall.invoke({"key": "nonexistent"})
        assert "No memory found" in result
