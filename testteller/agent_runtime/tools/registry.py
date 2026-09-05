"""Small typed tool registry with traceable results.

The registry intentionally does not execute arbitrary model-provided Python.
Each tool is registered by application code and receives validated arguments.
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


ToolCallable = Callable[..., Any] | Callable[..., Awaitable[Any]]


class AgentToolRegistry:
    """Register and invoke a least-privilege set of agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolCallable] = {}
        self._descriptions: dict[str, str] = {}
        self._schemas: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []

    def register(self, name: str, tool: ToolCallable, description: str = "",
                 args_schema: Any | None = None) -> None:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"Invalid tool name: {name!r}")
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool
        self._descriptions[name] = description or f"Invoke the {name} application tool."
        self._schemas[name] = args_schema

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def invoke(self, name: str, **kwargs: Any) -> ToolResult:
        if name not in self._tools:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        started = time.perf_counter()
        try:
            value = self._tools[name](**kwargs)
            if inspect.isawaitable(value):
                value = await value
            result = ToolResult(ok=True, data=value)
        except Exception as exc:  # Tool errors become observable state, not hidden failures.
            result = ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        result.duration_ms = (time.perf_counter() - started) * 1000
        self.calls.append({"tool": name, "arguments": kwargs, "result": result.as_dict()})
        return result

    def as_langchain_tools(self, names: list[str] | None = None) -> list[Any]:
        """Expose the same allowlisted tools as LangChain StructuredTool objects."""
        from langchain_core.tools import StructuredTool

        selected = names or self.names()
        tools = []
        for name in selected:
            if name not in self._tools:
                raise ValueError(f"Unknown tool: {name}")
            function = self._tools[name]
            kwargs = {
                "name": name,
                "description": self._descriptions[name],
                "args_schema": self._schemas[name],
            }
            if inspect.iscoroutinefunction(function):
                kwargs["coroutine"] = function
            else:
                kwargs["func"] = function
            tools.append(StructuredTool.from_function(**kwargs))
        return tools
