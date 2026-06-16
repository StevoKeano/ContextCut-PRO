"""
Shared fixtures and configuration for ContextCut-PRO test suite.
"""

import io
import sys
import types
import json
import email.message
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest


def _ensure_ddgs():
    """Make ``from ddgs import DDGS`` importable when duckduckgo_search is absent."""
    if "ddgs" not in sys.modules:
        ddgs_mod = types.ModuleType("ddgs")
        ddgs_mod.DDGS = MagicMock
        sys.modules["ddgs"] = ddgs_mod


_ensure_ddgs()

# voyageai triggers a broken dependency chain (spacy → typer → click)
# on Python 3.13 / Windows.  Stub it so qdrant_proxy_final's import
# resolves via sys.modules instead of loading the real package.
if "voyageai" not in sys.modules:
    sys.modules["voyageai"] = types.ModuleType("voyageai")


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", default=False, help="Run live integration tests"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip_live = pytest.mark.skip(reason="use --live to run")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)


@pytest.fixture
def make_handler():
    """Factory fixture for testing DashboardHandler (or ProxyHandler) without a running server.

    Returns a callable: ``(path, method, body=b'', handler_cls=None) -> (status_code, body_bytes)``
    where *body_bytes* is everything the handler wrote to *wfile*.
    """
    from qdrant_proxy_final import DashboardHandler

    def _make(path="/", method="GET", body=b"", handler_cls=None):
        handler_cls = handler_cls or DashboardHandler
        handler = handler_cls.__new__(handler_cls)
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.command = method
        handler.path = path
        handler.headers = email.message.Message()
        if body:
            handler.headers["Content-Length"] = str(len(body))
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.close_connection = True
        handler.request_version = "HTTP/1.1"
        handler.server_version = "BaseHTTP/0.6"
        handler.sys_version = "Python/3.x"

        captured_status = [200]
        orig_send = handler.send_response

        def _send_response(code, message=None):
            captured_status[0] = code
            return orig_send(code, message)

        handler.send_response = _send_response

        method_map = {
            "GET": getattr(handler_cls, "do_GET", None),
            "POST": getattr(handler_cls, "do_POST", None),
            "DELETE": getattr(handler_cls, "do_DELETE", None),
        }
        do_method = method_map.get(method)
        if do_method:
            do_method(handler)
        else:
            handler.send_error(405, "Method Not Allowed")

        raw = handler.wfile.getvalue()
        return captured_status[0], raw

    return _make


@pytest.fixture
def mock_qdrant_client():
    """Return a MagicMock spec'ed as QdrantClient."""
    from qdrant_client import QdrantClient

    return MagicMock(spec=QdrantClient)


@pytest.fixture
def mock_subprocess():
    """Patch ``agent_handler._run_subprocess``."""
    with patch("agent_handler._run_subprocess") as m:
        yield m


@pytest.fixture
def mock_sqlite():
    """Patch ``sqlite3.connect`` to return a MagicMock."""
    with patch("sqlite3.connect") as m:
        yield m


@pytest.fixture
def mock_sessions():
    """Return a fresh in-memory session dict matching ``_sessions`` structure."""
    return {
        "abc12345": {
            "history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
            "created": "2025-01-01T00:00:00",
            "msg_count": 2,
            "ctx_limit_reached": False,
            "shell_confirm_mode": "ask",
            "_db_inserted": False,
        }
    }
