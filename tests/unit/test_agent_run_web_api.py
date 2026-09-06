from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from testteller.agent_runtime.graph import AgenticTestWorkflow
from testteller.agent_runtime.service import PreparedAgentRun
from testteller.web.app import app, job_manager


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_get_nonexistent_agent_run(client):
    res = client.get("/api/agent-runs/non-existent-id")
    assert res.status_code == 404


def test_resume_invalid_agent_run(client):
    res = client.post("/api/agent-runs/non-existent-id/resume", json={"decision": "approve"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_agent_run_api_lifecycle(tmp_path: Path):
    sample_file = tmp_path / "test.md"
    sample_file.write_text("# Test\n## TC1\nSteps: 1\n", encoding="utf-8")

    async def fake_generator(state):
        return {
            "app.py": "def compute(x):\n    return x * 2\n",
            "tests/test_run.py": "from app import compute\n\ndef test_f():\n    res = compute(21)\n    assert res == 42\n",
        }

    workflow = AgenticTestWorkflow(generator=fake_generator)

    fake_prepared = PreparedAgentRun(
        task_id="test-task-1",
        workspace=tmp_path,
        trace_path=tmp_path / "trace.jsonl",
        language="python",
        framework="pytest",
        test_command=["python", "-m", "pytest", "-q"],
        test_cases=[],
        llm_manager=None,
        vector_store=AsyncMock(close=AsyncMock()),
        workflow=workflow,
        initial_state={
            "task_id": "test-task-1",
            "workspace": str(tmp_path),
            "test_command": ["python", "-m", "pytest", "-q"],
            "human_review": False,
            "target_entrypoint": "app.compute",
            "evidence_catalog": [
                {
                    "evidence_id": "EV-APP-COMPUTE",
                    "kind": "target_symbol",
                    "value": "app.compute",
                    "source": "app.py",
                    "source_id": "s1",
                    "source_path": "app.py",
                    "source_chunk_id": "c1",
                    "trust_level": "T0_AUTHORITATIVE",
                    "extractor": "ast_extractor",
                }
            ],
        },
    )

    with patch("testteller.web.app.prepare_agent_run", return_value=fake_prepared):
        with TestClient(app) as client:
            res = client.post("/api/agent-runs", json={
                "input_file": str(sample_file),
                "framework": "pytest",
            })
            assert res.status_code == 200
            task_id = res.json()["task_id"]
            assert task_id

            for _ in range(50):
                await asyncio.sleep(0.1)
                info = client.get(f"/api/agent-runs/{task_id}").json()
                if info["status"] in ("PASS", "FAILED", "ERROR"):
                    break

            assert info["status"] == "PASS"
            assert info["final_verdict"] == "PASS"

            # Check SSE endpoint replay
            sse_res = client.get(f"/api/agent-runs/{task_id}/events")
            assert sse_res.status_code == 200
            content = sse_res.text
            assert "RUN_STARTED" in content
            assert "RUN_COMPLETED" in content

            # Verify no duplicate lifecycle events
            job = job_manager.get_job(task_id)
            assert job is not None
            event_types = [e.get("event") for e in job.events_history]
            assert event_types.count("RUN_STARTED") == 1
            assert event_types.count("RUN_COMPLETED") == 1



@pytest.mark.asyncio
async def test_agent_run_hitl_resume(tmp_path: Path):
    sample_file = tmp_path / "test.md"
    sample_file.write_text("# Test\n## TC1\nSteps: 1\n", encoding="utf-8")

    async def fake_generator(state):
        return {"test_fail.py": "def test_fail():\n    assert False\n"}

    workflow = AgenticTestWorkflow(
        generator=fake_generator,
        checkpoint_path=str(tmp_path / "check.sqlite"),
    )

    fake_prepared = PreparedAgentRun(
        task_id="test-task-hitl",
        workspace=tmp_path,
        trace_path=tmp_path / "trace.jsonl",
        language="python",
        framework="pytest",
        test_command=["python", "-m", "pytest", "-q"],
        test_cases=[],
        llm_manager=None,
        vector_store=AsyncMock(close=AsyncMock()),
        workflow=workflow,
        initial_state={
            "task_id": "test-task-hitl",
            "workspace": str(tmp_path),
            "test_command": ["python", "-m", "pytest", "-q"],
            "human_review": True,
            "max_repair_rounds": 0,
        },
    )

    with patch("testteller.web.app.prepare_agent_run", return_value=fake_prepared):
        with TestClient(app) as client:
            res = client.post("/api/agent-runs", json={
                "input_file": str(sample_file),
                "framework": "pytest",
                "human_review": True,
            })
            assert res.status_code == 200
            task_id = res.json()["task_id"]

            for _ in range(50):
                await asyncio.sleep(0.1)
                info = client.get(f"/api/agent-runs/{task_id}").json()
                if info["status"] == "WAITING_REVIEW":
                    break

            assert info["status"] == "WAITING_REVIEW"

            # Resume with approve
            res = client.post(f"/api/agent-runs/{task_id}/resume", json={"decision": "approve"})
            assert res.status_code == 200
            assert res.json()["status"] in ("PASS", "APPROVED", "MANUAL_APPROVED")

            info = client.get(f"/api/agent-runs/{task_id}").json()
            assert info["status"] in ("PASS", "APPROVED", "MANUAL_APPROVED")

            # Verify no duplicate lifecycle events for HITL resume run
            job = job_manager.get_job(task_id)
            assert job is not None
            event_types = [e.get("event") for e in job.events_history]
            assert event_types.count("RUN_STARTED") == 1
            assert event_types.count("WAITING_REVIEW") == 1
            assert event_types.count("RUN_RESUMED") == 1
            assert event_types.count("RUN_COMPLETED") == 1


@pytest.mark.asyncio
async def test_sse_event_ordering_and_review_decoupling(tmp_path: Path):
    sample_file = tmp_path / "test.md"
    sample_file.write_text("# Test\n## TC1\nSteps: 1\n", encoding="utf-8")

    async def fake_generator(state):
        return {
            "app.py": "def compute(x):\n    return x * 2\n",
            "tests/test_run.py": "from app import compute\n\ndef test_f():\n    res = compute(21)\n    assert res == 42\n",
        }

    workflow = AgenticTestWorkflow(generator=fake_generator)

    fake_prepared = PreparedAgentRun(
        task_id="test-task-ordering",
        workspace=tmp_path,
        trace_path=tmp_path / "trace.jsonl",
        language="python",
        framework="pytest",
        test_command=["python", "-m", "pytest", "-q"],
        test_cases=[],
        llm_manager=None,
        vector_store=AsyncMock(close=AsyncMock()),
        workflow=workflow,
        initial_state={
            "task_id": "test-task-ordering",
            "workspace": str(tmp_path),
            "test_command": ["python", "-m", "pytest", "-q"],
            "human_review": False,
            "target_entrypoint": "app.compute",
            "evidence_catalog": [
                {
                    "evidence_id": "EV-APP-COMPUTE",
                    "kind": "target_symbol",
                    "value": "app.compute",
                    "source": "app.py",
                    "source_id": "s1",
                    "source_path": "app.py",
                    "source_chunk_id": "c1",
                    "trust_level": "T0_AUTHORITATIVE",
                    "extractor": "ast_extractor",
                }
            ],
        },
    )

    with patch("testteller.web.app.prepare_agent_run", return_value=fake_prepared):
        with TestClient(app) as client:
            res = client.post("/api/agent-runs", json={
                "input_file": str(sample_file),
                "framework": "pytest",
            })
            assert res.status_code == 200
            task_id = res.json()["task_id"]

            for _ in range(50):
                await asyncio.sleep(0.1)
                info = client.get(f"/api/agent-runs/{task_id}").json()
                if info["status"] in ("PASS", "FAILED", "ERROR"):
                    break

            sse_res = client.get(f"/api/agent-runs/{task_id}/events")
            assert sse_res.status_code == 200
            sse_content = sse_res.text
            sse_events = [line.split("event: ")[1].strip() for line in sse_content.splitlines() if line.startswith("event: ")]

            # 1. Zero duplication assertion on SSE replay stream
            assert sse_events.count("RUN_STARTED") == 1
            assert sse_events.count("RUN_COMPLETED") == 1

            # 2. Strict sequential order: review completed occurs BEFORE run completed
            assert "REVIEW_COMPLETED" in sse_events
            assert "RUN_COMPLETED" in sse_events
            idx_review = sse_events.index("REVIEW_COMPLETED")
            idx_completed = sse_events.index("RUN_COMPLETED")
            assert idx_review < idx_completed, "REVIEW_COMPLETED must arrive before RUN_COMPLETED"

            # 3. Payload contract verification:
            # REVIEW_COMPLETED payload contains 'verdict', RUN_COMPLETED payload contains 'final_verdict'
            job = job_manager.get_job(task_id)
            assert job is not None
            review_events = [e for e in job.events_history if e.get("event") == "REVIEW_COMPLETED"]
            completed_events = [e for e in job.events_history if e.get("event") == "RUN_COMPLETED"]
            assert len(review_events) == 1
            assert len(completed_events) == 1
            assert "verdict" in review_events[0]
            assert "final_verdict" in completed_events[0]
            assert completed_events[0]["final_verdict"] == "PASS"



