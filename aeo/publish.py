"""Sandbox publisher for AEO content experiments.

The first slice never talks to a live CMS.  It copies the approved content
workspace into a separate sandbox directory and can restore the prior snapshot.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Iterable


class SandboxPublisher:
    def __init__(self, source_root: str | Path, target_root: str | Path):
        self.source_root = Path(source_root).expanduser().resolve()
        self.target_root = Path(target_root).expanduser().resolve()
        self.target_root.mkdir(parents=True, exist_ok=True)

    def _safe_target(self, relative: str | Path) -> Path:
        candidate = (self.target_root / relative).expanduser().resolve()
        try:
            candidate.relative_to(self.target_root)
        except ValueError as exc:
            raise ValueError(f"path escapes publish root: {relative}") from exc
        return candidate

    def snapshot(self, suffixes: Iterable[str] = (".md", ".markdown")) -> dict[str, str]:
        allowed = {suffix.lower() for suffix in suffixes}
        snapshot: dict[str, str] = {}
        for path in sorted(self.target_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in allowed:
                relative = path.relative_to(self.target_root).as_posix()
                snapshot[relative] = path.read_text(encoding="utf-8")
        return snapshot

    def publish(
        self,
        paths: Iterable[str],
        *,
        remove_missing: bool = False,
    ) -> dict:
        published: list[str] = []
        for relative in paths:
            source = (self.source_root / relative).expanduser().resolve()
            try:
                source.relative_to(self.source_root)
            except ValueError as exc:
                raise ValueError(f"path escapes source root: {relative}") from exc
            if not source.is_file():
                raise FileNotFoundError(f"source file not found: {relative}")
            target = self._safe_target(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            published.append(str(relative))

        if remove_missing:
            keep = {str(path) for path in paths}
            for relative in self.snapshot():
                if relative not in keep:
                    self._safe_target(relative).unlink(missing_ok=True)

        return {
            "published": published,
            "target_root": str(self.target_root),
            "manifest": self.manifest(),
        }

    def rollback(self, snapshot: dict[str, str], *, remove_new: bool = True) -> None:
        for relative, content in snapshot.items():
            target = self._safe_target(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if remove_new:
            keep = {str(path) for path in snapshot}
            for relative in self.snapshot():
                if relative not in keep:
                    self._safe_target(relative).unlink(missing_ok=True)

    def manifest(self) -> dict[str, str]:
        manifest: dict[str, str] = {}
        for path in sorted(self.target_root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(self.target_root).as_posix()
                manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return manifest
