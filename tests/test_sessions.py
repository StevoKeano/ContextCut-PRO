"""
Tests for session lifecycle: new, add, get, clear.
"""

import pytest
from unittest.mock import patch


class TestSessionLifecycle:
    @patch("qdrant_proxy_final._sessions", {})
    @patch("qdrant_proxy_final._current_sid", None)
    def test_new_session_creates_8char_uuid(self):
        from qdrant_proxy_final import new_session, _sessions

        sid = new_session()
        assert len(sid) == 8
        assert sid in _sessions
        assert _sessions[sid]["history"] == []
        assert _sessions[sid]["msg_count"] == 0

    @patch("qdrant_proxy_final._sessions", {})
    @patch("qdrant_proxy_final._current_sid", None)
    def test_add_to_history_inserts_message(self):
        from qdrant_proxy_final import new_session, add_to_history

        sid = new_session()
        add_to_history(sid, "user", "test message")
        from qdrant_proxy_final import _sessions

        assert _sessions[sid]["msg_count"] == 1
        assert len(_sessions[sid]["history"]) == 1
        assert _sessions[sid]["history"][0]["role"] == "user"
        assert _sessions[sid]["history"][0]["content"] == "test message"

    @patch("qdrant_proxy_final._sessions", {})
    @patch("qdrant_proxy_final._current_sid", None)
    def test_get_session_returns_correct_session(self):
        from qdrant_proxy_final import new_session, get_session

        sid = new_session()
        session = get_session(sid)
        assert session is not None
        assert session["msg_count"] == 0

    def test_get_session_returns_none_for_unknown(self):
        from qdrant_proxy_final import get_session

        assert get_session("nonexistent") is None

    @patch("qdrant_proxy_final._sessions", {})
    @patch("qdrant_proxy_final._current_sid", None)
    def test_clear_session_removes_session(self):
        from qdrant_proxy_final import new_session, clear_session, get_session

        sid = new_session()
        assert get_session(sid) is not None
        clear_session(sid)
        session = get_session(sid)
        assert session is not None
        assert session["history"] == []
        assert session["msg_count"] == 0

    @patch("qdrant_proxy_final._sessions", {})
    @patch("qdrant_proxy_final._current_sid", None)
    def test_increment_msg_count(self):
        from qdrant_proxy_final import new_session, add_to_history

        sid = new_session()
        for i in range(5):
            add_to_history(sid, "user", f"msg {i}")
        from qdrant_proxy_final import _sessions as s

        assert s[sid]["msg_count"] == 5
