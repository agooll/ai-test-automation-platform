from pathlib import Path

import pytest

from testteller.agent_runtime.graph import AgenticTestWorkflow


@pytest.mark.asyncio
async def test_sqlite_checkpoint_can_resume_same_thread(tmp_path: Path):
    workflow = AgenticTestWorkflow(
        checkpoint_path=str(tmp_path / "agent_state.sqlite"),
        generator=lambda state: {"test.py": "def test_bad():\n    assert False\n"},
    )
    thread_id = "checkpoint-test"
    result = await workflow.run({
        "requirement": "checkpoint",
        "workspace": str(tmp_path),
        "test_command": ["python", "-m", "pytest", "-q"],
        "human_review": True,
        "max_repair_rounds": 0,
    }, thread_id=thread_id)
    assert "__interrupt__" in result
    resumed = await workflow.resume(thread_id, "reject")
    assert resumed["final_verdict"] == "REJECTED"
    await workflow.aclose()
