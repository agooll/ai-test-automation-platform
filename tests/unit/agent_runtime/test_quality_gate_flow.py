"""Tests verifying that LangGraph workflow properly routes through code_quality and enforces invariant."""

from pathlib import Path
import pytest
from testteller.agent_runtime.graph import AgenticTestWorkflow
from testteller.agent_runtime.state import AgentState
from testteller.agent_runtime.tools import AgentToolRegistry
from testteller.quality_gate.code_gate import AutomationCodeQualityGate

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_fake_test_rejected_even_if_execution_passes(tmp_path: Path):
    """Verify invariant: execution_passed=True but code_quality=REJECTED -> final_verdict != PASS."""
    def fake_generator(state: AgentState):
        return {
            "tests/test_fake.py": "def test_fake(): assert True"
        }

    events = []
    def sink(event):
        events.append(event)

    tools = AgentToolRegistry()
    async def mock_run_tests(workspace, command, framework, task_id=None):
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=fake_generator,
        tool_registry=tools,
        event_sink=sink,
    )

    result = await workflow.run({
        "requirement": "Test login",
        "workspace": str(tmp_path),
    })

    # Code quality gate must have recorded violations
    assert result["code_quality_result"]["status"] == "REJECTED"
    assert result["vacuity_score"] < 1.0

    # Invariant: final_verdict CANNOT be PASS!
    assert result["final_verdict"] == "REJECTED"

    # Event CODE_QUALITY_COMPLETED must have been emitted
    event_names = [e["event"] for e in events]
    assert "CODE_QUALITY_COMPLETED" in event_names


@pytest.mark.asyncio
async def test_clean_test_produces_pass(tmp_path: Path):
    """Verify that a valid test passing both execution and code quality produces final_verdict=PASS."""
    def clean_generator(state: AgentState):
        return {
            "tests/test_real.py": """
from cachetools import LRUCache

def test_cache_put():
    c = LRUCache(maxsize=1)
    c['k'] = 'v'
    assert c['k'] == 'v'
"""
        }

    tools = AgentToolRegistry()
    async def mock_run_tests(workspace, command, framework, task_id=None):
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=clean_generator,
        tool_registry=tools,
    )

    result = await workflow.run({
        "requirement": "Test LRU cache",
        "workspace": str(tmp_path),
        "target_entrypoint": "cachetools.LRUCache",
    })

    assert result["code_quality_result"]["status"] == "PASS"
    assert result["vacuity_score"] == 1.0
    assert result["execution_result"]["passed"] is True
    assert result["final_verdict"] == "PASS"
