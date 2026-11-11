"""LangChain tools for the AEO content workspace.

Callers pass these tools through ``agent_handler.build_agent(extra_tools=...)``.
The high-impact tools are named ``content_write`` and ``publish_content`` so the
human-in-the-loop middleware can pause them.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain.tools import tool

from .content_store import ContentStore
from .publish import SandboxPublisher


def make_content_tools(
    content_root: str | Path,
    publish_root: str | Path | None = None,
) -> list:
    content = ContentStore(content_root)
    target = (
        Path(publish_root).expanduser().resolve()
        if publish_root
        else (Path(content_root).expanduser().resolve().parent / "published")
    )
    publisher = SandboxPublisher(content.root, target)

    @tool
    def content_list() -> str:
        """List Markdown files in the AEO content workspace."""
        return json.dumps(content.list_documents(), indent=2)

    @tool
    def content_read(path: str) -> str:
        """Read a Markdown file from the AEO content workspace."""
        return content.read(path)

    @tool
    def content_write(path: str, text: str) -> str:
        """Write a Markdown file in the AEO content workspace.

        Requires human approval before execution.
        """
        content.write(path, text)
        return f"Wrote {len(text.encode('utf-8'))} bytes to {path}"

    @tool
    def publish_content(paths: str) -> str:
        """Publish comma-separated Markdown paths to the sandbox.

        Requires human approval before execution.
        """
        selected = [item.strip() for item in paths.split(",") if item.strip()]
        if not selected:
            raise ValueError("at least one path is required")
        result = publisher.publish(selected)
        return json.dumps(result, indent=2)

    return [content_list, content_read, content_write, publish_content]
