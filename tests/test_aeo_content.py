"""Tests for AEO mock providers and the local content/publish adapters."""

from __future__ import annotations

import pytest

from aeo.content_store import ContentStore
from aeo.providers import MockAEOProvider, MockAnalyticsProvider
from aeo.publish import SandboxPublisher


QUERIES = [f"query {index}" for index in range(20)]


def test_mock_citation_scenarios_are_deterministic():
    provider = MockAEOProvider()

    baseline = provider.measure("body", QUERIES, scenario="baseline")
    improved = provider.measure("body", QUERIES, scenario="improved")
    regressed = provider.measure("body", QUERIES, scenario="regressed")
    unchanged = provider.measure("body", QUERIES, scenario="no_change")

    assert baseline.citation_rate == 0.35
    assert improved.citation_rate == 0.65
    assert regressed.citation_rate == 0.15
    assert unchanged.citation_rate == baseline.citation_rate
    assert baseline.valid is True
    assert len(baseline.results) == len(QUERIES)


def test_mock_citation_invalid_and_unknown():
    provider = MockAEOProvider()

    invalid = provider.measure("body", QUERIES, scenario="invalid")
    assert invalid.citation_rate is None
    assert invalid.valid is False
    assert invalid.error

    unknown = provider.measure("body", QUERIES, scenario="nope")
    assert unknown.valid is False
    assert "unknown mock scenario" in unknown.error


def test_mock_analytics_is_deterministic():
    provider = MockAnalyticsProvider(base_views=1000)
    baseline = provider.measure("body", scenario="baseline")
    improved = provider.measure("body", scenario="improved")

    assert baseline["page_views"] == 1000
    assert improved["page_views"] > baseline["page_views"]
    assert baseline["content_hash"] == improved["content_hash"]


def test_content_store_apply_diff_and_rollback(tmp_path):
    store = ContentStore(tmp_path / "content")
    store.write("index.md", "# Title\n\nBody.\n")
    snapshot = store.snapshot()

    changes = store.apply_changes({"index.md": "# Title\n\nBody.\n\n## FAQ\n\nAnswer.\n"})

    assert len(changes) == 1
    assert "## FAQ" in changes[0].diff
    assert "## FAQ" in store.read("index.md")

    store.rollback(snapshot)
    assert store.read("index.md") == "# Title\n\nBody.\n"


def test_content_store_rejects_path_escape(tmp_path):
    store = ContentStore(tmp_path / "content")

    with pytest.raises(ValueError, match="escapes content root"):
        store.write("../outside.md", "nope")


def test_sandbox_publisher_publish_and_rollback(tmp_path):
    source = tmp_path / "content"
    source.mkdir()
    (source / "index.md").write_text("# New\n", encoding="utf-8")
    publisher = SandboxPublisher(source, tmp_path / "published")
    (tmp_path / "published").mkdir(parents=True, exist_ok=True)
    (tmp_path / "published" / "index.md").write_text("# Old\n", encoding="utf-8")

    before = publisher.snapshot()
    result = publisher.publish(["index.md"])

    assert result["published"] == ["index.md"]
    assert (tmp_path / "published" / "index.md").read_text() == "# New\n"
    assert "index.md" in result["manifest"]

    publisher.rollback(before)
    assert (tmp_path / "published" / "index.md").read_text() == "# Old\n"
