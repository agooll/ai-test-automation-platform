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


@pytest.mark.asyncio
async def test_production_agent_without_target_identity_rejects_unrelated_helper(tmp_path: Path):
    """
    Verify regression: Without target identity (target_entrypoint is None),
    the agent must NOT treat an unrelated helper function as SUT,
    and must fail-closed (final_verdict != PASS, allow_final_pass == False).
    """
    def helper_generator(state: AgentState):
        return {
            "tests/test_helper_fake.py": """
def my_unrelated_helper():
    return 42

def test_call_helper():
    val = my_unrelated_helper()
    assert val == 42
"""
        }

    tools = AgentToolRegistry()
    async def mock_run_tests(workspace, command, framework, task_id=None):
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=helper_generator,
        tool_registry=tools,
    )

    # Target identity is omitted/None
    result = await workflow.run({
        "requirement": "Test something without target identity",
        "workspace": str(tmp_path),
        "target_entrypoint": None,
    })

    cq_res = result["code_quality_result"]
    assert cq_res["status"] in ("REJECTED", "NEEDS_REVIEW")
    assert cq_res["allow_final_pass"] is False
    assert result["final_verdict"] != "PASS"

    from testteller.quality_gate.code_models import CodeViolationCode
    codes = [v["code"] for v in cq_res["hard_violations"]]
    assert CodeViolationCode.NO_SUT_INTERACTION.value in codes


@pytest.mark.asyncio
async def test_adapter_evidence_leads_codegate_to_supported_and_pass(tmp_path: Path):
    """
    Verify regression: Adapter retrieves ApplicationContext evidence items,
    injects them into grounding_catalog via retrieve node,
    and CodeGate verifies the claims as SUPPORTED, leading to PASS.
    """
    from unittest.mock import MagicMock
    from testteller.agent_runtime.adapters import ExistingRAGAdapter
    from testteller.automator_agent.application_context import ApplicationContext, APIEndpoint
    from testteller.automator_agent.parser.markdown_parser import TestCase

    # 1. Build an application context with an authoritative API endpoint
    app_ctx = ApplicationContext()
    ep = APIEndpoint(
        path="/api/v1/users",
        method="GET",
        description="List all active users",
        source_refs=["src/api/users.py"],
        evidence_ids=["EP-USERS-001"],
    )
    app_ctx.api_endpoints["GET /api/v1/users"] = ep

    # 2. Mock RAGEnhancedTestGenerator with vector store using query_collection branch
    mock_generator = MagicMock()
    mock_generator.knowledge_extractor.extract_app_context.return_value = app_ctx
    # Specifically test query_collection branch
    del mock_generator.knowledge_extractor.vector_store.query_similar
    mock_generator.knowledge_extractor.vector_store.query_collection = MagicMock(return_value=[])
    mock_generator.num_context_docs = 3

    test_cases = [
        TestCase(
            id="TC-01",
            feature="User Listing",
            type="INT",
            category="API",
            objective="Verify user listing endpoint",
        )
    ]

    adapter = ExistingRAGAdapter(
        generator=mock_generator,
        test_cases=test_cases,
        llm_manager=MagicMock(),
    )

    # 3. Define generator that generates a test exercising the verified endpoint
    def api_generator(state: AgentState):
        return {
            "tests/test_users_api.py": """
import requests

def test_list_users():
    response = requests.get("/api/v1/users")
    assert response.status_code == 200
"""
        }

    tools = AgentToolRegistry()
    async def mock_run_tests(workspace, command, framework, task_id=None):
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        retriever=adapter.retrieve,
        generator=api_generator,
        tool_registry=tools,
    )

    result = await workflow.run({
        "requirement": "Test user listing",
        "workspace": str(tmp_path),
        "target_entrypoint": "src.api.users",
    })

    # 4. Assert end-to-end evidence propagation and grounding verification
    cq_res = result["code_quality_result"]
    assert "grounding_catalog" in result
    assert len(result["grounding_catalog"]) > 0
    catalog_evidence_ids = [item.get("evidence_id") for item in result["grounding_catalog"]]
    assert "EP-USERS-001" in catalog_evidence_ids

    # Claim must be SUPPORTED by the retrieved evidence!
    findings = cq_res["grounding_findings"]
    api_findings = [f for f in findings if f["claim_type"] == "api_endpoint"]
    assert len(api_findings) > 0
    assert api_findings[0]["status"] == "SUPPORTED"
    assert api_findings[0]["evidence_id"] == "EP-USERS-001"

    # Status must be PASS, and final verdict must be PASS
    assert cq_res["status"] == "PASS"
    assert cq_res["allow_final_pass"] is True
    assert result["final_verdict"] == "PASS"


@pytest.mark.asyncio
async def test_workflow_blocks_repair_weakening(tmp_path: Path):
    """
    Verify Stage 4.4: When repair attempts to pass by weakening assertions,
    the workflow detects weakening, rejects execution, and prevents final PASS.
    """
    def initial_generator(state: AgentState):
        return {
            "tests/test_weakening.py": """
from cachetools import LRUCache

def test_cache_value():
    c = LRUCache(maxsize=10)
    c['k'] = 42
    assert c['k'] == 42
    assert len(c) == 1
"""
        }

    def weakening_repairer(state: AgentState):
        # Repaired version deleted an assertion and softened the other to is not None
        return {
            "tests/test_weakening.py": """
from cachetools import LRUCache

def test_cache_value():
    c = LRUCache(maxsize=10)
    c['k'] = 42
    assert c['k'] is not None
"""
        }

    exec_call_count = 0

    async def mock_run_tests(workspace, command, framework, task_id=None):
        nonlocal exec_call_count
        exec_call_count += 1
        # Fail on initial generation round
        return {"passed": False, "exit_code": 1, "stdout": "", "stderr": "AssertionError"}

    tools = AgentToolRegistry()
    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=initial_generator,
        repairer=weakening_repairer,
        tool_registry=tools,
    )

    result = await workflow.run({
        "requirement": "Verify LRU cache keys and count",
        "workspace": str(tmp_path),
        "target_entrypoint": "cachetools.LRUCache",
        "max_repair_rounds": 1,
    })

    # Weakening must be flagged
    assert result.get("weakening_detected") is True
    cq_res = result["code_quality_result"]
    assert cq_res["status"] == "REJECTED"
    assert cq_res["allow_final_pass"] is False
    assert result["final_verdict"] == "REJECTED"
    assert any("REPAIR_WEAKENED_ASSERTION" in fb or "REPAIR_EQUALITY_WEAKENED" in fb for fb in cq_res["repair_feedback"])


