import pytest

from testteller.agent_runtime.tools.registry import AgentToolRegistry


def test_registry_exposes_structured_langchain_tools():
    registry = AgentToolRegistry()

    def add(left: int, right: int) -> int:
        return left + right

    registry.register("add_numbers", add, description="Add two integers")
    tools = registry.as_langchain_tools()
    assert tools[0].name == "add_numbers"
    assert tools[0].invoke({"left": 2, "right": 3}) == 5


@pytest.mark.asyncio
async def test_registry_records_failed_tool_calls():
    registry = AgentToolRegistry()

    def explode(value: str) -> str:
        raise RuntimeError(value)

    registry.register("explode", explode)
    result = await registry.invoke("explode", value="bad")
    assert result.ok is False
    assert registry.calls[-1]["tool"] == "explode"
