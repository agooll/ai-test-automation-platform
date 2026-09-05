"""Workspace-bounded artifact tools."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping


class WorkspaceArtifacts:
    def __init__(self, workspace_root: str | Path) -> None:
        self.root = Path(workspace_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_files(self, files: Mapping[str, str]) -> list[str]:
        written: list[str] = []
        for relative_name, content in files.items():
            target = (self.root / relative_name).resolve()
            self._ensure_inside(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(str(target.relative_to(self.root)))
        return written

    def read_file(self, relative_name: str) -> str:
        target = (self.root / relative_name).resolve()
        self._ensure_inside(target)
        return target.read_text(encoding="utf-8")

    def _ensure_inside(self, target: Path) -> None:
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Artifact path escapes workspace: {target}") from exc

