"""Tests for the AEO LangChain tool factory."""

from __future__ import annotations

import json

from aeo.tools import make_content_tools


def test_content_tool_factory_names(tmp_path):
    tools = make_content_tools(tmp_path / "content", tmp_path / "published")

    assert [tool.name for tool in tools] == [
        "content_list",
        "content_read",
        "content_write",
        "publish_content",
    ]


def test_content_tools_read_write_and_publish(tmp_path):
    content_root = tmp_path / "content"
    publish_root = tmp_path / "published"
    tools = {tool.name: tool for tool in make_content_tools(content_root, publish_root)}

    tools["content_write"].invoke({"path": "index.md", "text": "# New\n\nBody.\n"})

    assert tools["content_read"].invoke({"path": "index.md"}) == "# New\n\nBody.\n"
    assert json.loads(tools["content_list"].invoke({})) == ["index.md"]

    result = json.loads(tools["publish_content"].invoke({"paths": "index.md"}))
    assert result["published"] == ["index.md"]
    assert publish_root.joinpath("index.md").read_text(encoding="utf-8") == "# New\n\nBody.\n"
