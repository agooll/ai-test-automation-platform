"""Checkpoint factory for resumable Agent runs."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver


class CheckpointStore:
    """Own the lifetime of a LangGraph checkpointer and its SQLite connection."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._stack = ExitStack()
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            from langgraph.checkpoint.sqlite import SqliteSaver
            self.checkpointer: Any = self._stack.enter_context(
                SqliteSaver.from_conn_string(str(self.path))
            )
        else:
            self.checkpointer = MemorySaver()

    def close(self) -> None:
        self._stack.close()

    def __enter__(self) -> "CheckpointStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AsyncCheckpointStore:
    """Async SQLite store required by LangGraph's ``ainvoke`` API."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._context = None
        self.checkpointer: Any | None = None

    async def start(self) -> Any:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        self._context = AsyncSqliteSaver.from_conn_string(str(self.path))
        self.checkpointer = await self._context.__aenter__()
        return self.checkpointer

    async def close(self) -> None:
        if self._context:
            await self._context.__aexit__(None, None, None)
            self._context = None
