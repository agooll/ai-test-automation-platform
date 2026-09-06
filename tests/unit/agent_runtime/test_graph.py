from pathlib import Path

import pytest

from testteller.agent_runtime.graph import AgenticTestWorkflow


@pytest.mark.asyncio
async def test_graph_passes_and_records_trace(tmp_path: Path):
    def generator(state):
        return {
            "calculator.py": "def compute(x):\n    return x * 2\n",
            "test_ok.py": "from calculator import compute\n\ndef test_ok():\n    res = compute(21)\n    assert res == 42\n",
        }

    evidence = [
        {
            "evidence_id": "EV-CALC-COMPUTE",
            "kind": "target_symbol",
            "value": "calculator.compute",
            "source": "calculator.py",
            "source_id": "s1",
            "source_path": "calculator.py",
            "source_chunk_id": "c1",
            "trust_level": "T0_AUTHORITATIVE",
            "extractor": "ast_extractor",
        }
    ]
    workflow = AgenticTestWorkflow(generator=generator)
    result = await workflow.run({
        "requirement": "Generate a passing smoke test",
        "workspace": str(tmp_path),
        "target_entrypoint": "calculator.compute",
        "evidence_catalog": evidence,
        "test_command": ["python", "-m", "pytest", "-q"],
        "framework": "pytest",
    })

    assert result["final_verdict"] == "PASS"
    assert result["execution_result"]["passed"] is True
    assert result["generation_success"] is True
    assert result["execution_success"] is True
    assert result["repair_success"] is False
    assert [event["node"] for event in result["trace"] if "node" in event] == [
        "plan", "grounding_plan", "retrieve", "evidence_build", "generate", "claim_bind", "code_quality", "execute", "review", "persist"
    ]


@pytest.mark.asyncio
async def test_graph_repairs_after_failure(tmp_path: Path):
    attempts = {"count": 0}

    def generator(state):
        return {
            "calculator.py": "def compute(x):\n    return x * 2\n",
            "test_case.py": "from calculator import compute\n\ndef test_case():\n    res = compute(21)\n    assert res == 40\n",
        }

    def repairer(state):
        attempts["count"] += 1
        return {
            "test_case.py": "from calculator import compute\n\ndef test_case():\n    res = compute(21)\n    assert res == 42\n",
        }

    evidence = [
        {
            "evidence_id": "EV-CALC-COMPUTE",
            "kind": "target_symbol",
            "value": "calculator.compute",
            "source": "calculator.py",
            "source_id": "s1",
            "source_path": "calculator.py",
            "source_chunk_id": "c1",
            "trust_level": "T0_AUTHORITATIVE",
            "extractor": "ast_extractor",
        }
    ]
    workflow = AgenticTestWorkflow(generator=generator, repairer=repairer)
    result = await workflow.run({
        "requirement": "Generate and validate a smoke test",
        "workspace": str(tmp_path),
        "target_entrypoint": "calculator.compute",
        "evidence_catalog": evidence,
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
    assert "code_quality" in [event["node"] for event in result["trace"]]
    assert (tmp_path / "trace.jsonl").read_text(encoding="utf-8").count("\n") == len(result["trace"])

    # Verify repair_history multi-round diff tracking
    assert len(result["repair_history"]) == 1
    first_repair = result["repair_history"][0]
    assert first_repair["round"] == 1
    assert first_repair["re_execution_passed"] is True
    assert "test_case.py" in first_repair["files"]
    diff = first_repair["files"]["test_case.py"]["diff"]
    assert "-    assert res == 40" in diff
    assert "+    assert res == 42" in diff
