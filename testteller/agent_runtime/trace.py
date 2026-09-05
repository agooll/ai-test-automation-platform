"""Append-only JSONL trace persistence for reproducible agent runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TraceRecorder:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def write_run(self, state: dict[str, Any]) -> None:
        for event in state.get("trace", []):
            self.append({"task_id": state.get("task_id"), **event})

