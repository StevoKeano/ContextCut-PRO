"""Filesystem-backed Markdown content workspace.

This is intentionally boring: a local directory of text files with safe path
handling, snapshots, diffs, and rollback.  A real CMS adapter can implement the
same operations later.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class FileChange:
    path: str
    before: str
    after: str
    diff: str

    def to_dict(self) -> dict:
        return asdict(self)


class ContentStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).expanduser().resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"path escapes content root: {relative}") from exc
        return candidate

    def list_documents(self, suffixes: Iterable[str] = (".md", ".markdown")) -> list[str]:
        allowed = {suffix.lower() for suffix in suffixes}
        documents = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.suffix.lower() in allowed:
                documents.append(path.relative_to(self.root).as_posix())
        return documents

    def exists(self, relative: str | Path) -> bool:
        return self._safe_path(relative).is_file()

    def read(self, relative: str | Path) -> str:
        path = self._safe_path(relative)
        if not path.is_file():
            raise FileNotFoundError(f"content file not found: {relative}")
        return path.read_text(encoding="utf-8")

    def write(self, relative: str | Path, content: str) -> None:
        path = self._safe_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def snapshot(self, paths: Iterable[str] | None = None) -> dict[str, str]:
        selected = list(paths) if paths is not None else self.list_documents()
        snapshot: dict[str, str] = {}
        for relative in selected:
            snapshot[str(relative)] = self.read(relative)
        return snapshot

    def apply_changes(self, changes: dict[str, str]) -> list[FileChange]:
        applied: list[FileChange] = []
        for relative, after in changes.items():
            before = self.read(relative) if self.exists(relative) else ""
            if before == after:
                continue
            diff = self.diff_text(relative, before, after)
            self.write(relative, after)
            applied.append(FileChange(relative, before, after, diff))
        return applied

    def diff(self, before: dict[str, str], paths: Iterable[str] | None = None) -> str:
        selected = list(paths) if paths is not None else sorted(before)
        chunks: list[str] = []
        for relative in selected:
            before_text = before.get(str(relative), "")
            after_text = self.read(relative) if self.exists(relative) else ""
            if before_text != after_text:
                chunks.append(self.diff_text(str(relative), before_text, after_text))
        return "\n".join(chunk for chunk in chunks if chunk)

    def rollback(self, snapshot: dict[str, str], *, remove_new: bool = True) -> None:
        for relative, content in snapshot.items():
            self.write(relative, content)
        if remove_new:
            keep = {str(path) for path in snapshot}
            for relative in self.list_documents():
                if relative not in keep:
                    self._safe_path(relative).unlink(missing_ok=True)

    @staticmethod
    def diff_text(relative: str, before: str, after: str) -> str:
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )
