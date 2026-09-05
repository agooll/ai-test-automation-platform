from pathlib import Path

import pytest

from testteller.agent_runtime.graph import AgenticTestWorkflow


@pytest.mark.asyncio
async def test_graph_passes_and_records_trace(tmp_path: Path):
    def generator(state):
        return {"test_ok.py": "def test_ok():\n    assert True\n"}

    workflow = AgenticTestWorkflow(generator=generator)
    result = await workflow.run({
        "requirement": "Generate a passing smoke test",
        "workspace": str(tmp_path),
        "test_command": ["python", "-m", "pytest", "-q"],
        "framework": "pytest",
    })

    assert result["final_verdict"] == "PASS"
    assert result["execution_result"]["passed"] is True
    assert result["generation_success"] is True
    assert result["execution_success"] is True
    assert result["repair_success"] is False
    assert [event["node"] for event in result["trace"]] == [
        "plan", "retrieve", "generate", "execute", "review", "persist"
    ]


@pytest.mark.asyncio
async def test_graph_repairs_after_failure(tmp_path: Path):
    attempts = {"count": 0}

    def generator(state):
        return {"test_case.py": "def test_case():\n    assert False\n"}

    def repairer(state):
        attempts["count"] += 1
        return {"test_case.py": "def test_case():\n    assert True\n"}

    workflow = AgenticTestWorkflow(generator=generator, repairer=repairer)
    result = await workflow.run({
        "requirement": "Generate and validate a smoke test",
        "workspace": str(tmp_path),
        "test_command": ["python", "-m", "pytest", "-q"],
        "framework": "pytest",
        "max_repair_rounds": 2,
        "trace_path": str(tmp_path / "trace.jsonl"),
    })

    assert result["final_verdict"] == "PASS"
    assert attempts["count"] == 1
    assert result["repair_round"] == 1
    assert result["repair_success"] is True
    assert "analyze_failure" in [event["node"] for event in result["trace"]]
    assert (tmp_path / "trace.jsonl").read_text(encoding="utf-8").count("\n") == len(result["trace"])
