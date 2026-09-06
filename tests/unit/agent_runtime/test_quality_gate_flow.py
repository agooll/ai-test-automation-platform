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


@pytest.mark.asyncio
async def test_repair_weakening_cannot_be_laundered_across_multiple_rounds(tmp_path: Path):
    """
    Verify regression for '两轮洗白':
    Round 0 (initial): test with 2 assertions (assert c['k'] == 42 and assert len(c) == 1).
    Round 1 (repair): weakens by deleting assert len(c) == 1. Gate flags and execution fails.
    Round 2 (repair): keeps the weakened assertions from Round 1 and adds a comment (attempting to launder).
                      Execution passes.
    Invariant: Because quality gate checks against the initial baseline, Round 2 MUST still be
               flagged as REPAIR_WEAKENED_ASSERTION and final_verdict MUST NOT be PASS.
    """
    def initial_generator(state: AgentState):
        return {
            "tests/test_multi_round.py": """
from cachetools import LRUCache

def test_cache():
    c = LRUCache(maxsize=10)
    c['k'] = 42
    assert c['k'] == 42
    assert len(c) == 1
"""
        }

    def laundering_repairer(state: AgentState):
        current_round = state.get("repair_round", 0)
        if current_round == 0:
            # Round 1: delete assert len(c) == 1
            return {
                "tests/test_multi_round.py": """
from cachetools import LRUCache

def test_cache():
    c = LRUCache(maxsize=10)
    c['k'] = 42
    assert c['k'] == 42
"""
            }
        else:
            # Round 2: attempt to launder by keeping round 1's code and adding a comment
            return {
                "tests/test_multi_round.py": """
from cachetools import LRUCache

def test_cache():
    # Attempting to launder the previous deletion across rounds
    c = LRUCache(maxsize=10)
    c['k'] = 42
    assert c['k'] == 42
"""
            }

    round_attempts = 0

    async def mock_run_tests(workspace, command, framework, task_id=None):
        nonlocal round_attempts
        round_attempts += 1
        # Round 0 & 1 fail, Round 2 execution passes
        if round_attempts < 3:
            return {"passed": False, "exit_code": 1, "stdout": "", "stderr": "AssertionError"}
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools = AgentToolRegistry()
    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=initial_generator,
        repairer=laundering_repairer,
        tool_registry=tools,
    )

    result = await workflow.run({
        "requirement": "Verify LRU cache keys and count",
        "workspace": str(tmp_path),
        "target_entrypoint": "cachetools.LRUCache",
        "max_repair_rounds": 2,
    })

    # Invariant: Round 2 must NOT launder the deletion from Round 0
    assert result.get("weakening_detected") is True
    cq_res = result["code_quality_result"]
    assert cq_res["status"] == "REJECTED"
    assert cq_res["allow_final_pass"] is False
    assert result["final_verdict"] == "REJECTED"

    violations = [v["code"] for v in cq_res["hard_violations"]]
    assert "REPAIR_WEAKENED_ASSERTION" in violations


@pytest.mark.asyncio
async def test_workflow_rejects_when_semantic_reviewer_fails(tmp_path: Path):
    """
    Verify integration: When execution passes and AST code quality passes,
    but the Semantic Reviewer returns status='fail', final_verdict MUST be REJECTED.
    """
    def clean_generator(state: AgentState):
        return {
            "tests/test_clean.py": """
from cachetools import LRUCache

def test_cache_op():
    c = LRUCache(maxsize=5)
    c['x'] = 100
    assert c['x'] == 100
"""
        }

    async def failing_reviewer(state: AgentState):
        return {
            "status": "fail",
            "requirement_alignment": 0.2,
            "assertion_strength": 0.3,
            "hallucination_risk": 0.8,
            "confidence": 0.9,
            "reason": "Test does not fulfill the requirement contract.",
        }

    tools = AgentToolRegistry()
    async def mock_run_tests(workspace, command, framework, task_id=None):
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=clean_generator,
        reviewer=failing_reviewer,
        tool_registry=tools,
    )

    result = await workflow.run({
        "requirement": "Verify LRU cache eviction under load",
        "workspace": str(tmp_path),
        "target_entrypoint": "cachetools.LRUCache",
    })

    assert result["execution_result"]["passed"] is True
    assert result["code_quality_result"]["status"] == "PASS"
    assert result["review"]["status"] == "fail"
    # Final verdict MUST be REJECTED
    assert result["final_verdict"] == "REJECTED"


@pytest.mark.asyncio
async def test_workflow_needs_review_when_semantic_reviewer_uncertain(tmp_path: Path):
    """
    Verify integration: When execution passes and AST code quality passes,
    but the Semantic Reviewer returns status='uncertain', final_verdict MUST be NEEDS_REVIEW.
    """
    def clean_generator(state: AgentState):
        return {
            "tests/test_clean.py": """
from cachetools import LRUCache

def test_cache_op():
    c = LRUCache(maxsize=5)
    c['x'] = 100
    assert c['x'] == 100
"""
        }

    async def uncertain_reviewer(state: AgentState):
        return {
            "status": "uncertain",
            "requirement_alignment": 0.5,
            "assertion_strength": 0.5,
            "hallucination_risk": 0.4,
            "confidence": 0.4,
            "reason": "Reviewer cannot determine if boundary requirements are fulfilled.",
        }

    tools = AgentToolRegistry()
    async def mock_run_tests(workspace, command, framework, task_id=None):
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=clean_generator,
        reviewer=uncertain_reviewer,
        tool_registry=tools,
    )

    result = await workflow.run({
        "requirement": "Verify LRU cache boundary behavior",
        "workspace": str(tmp_path),
        "target_entrypoint": "cachetools.LRUCache",
    })

    assert result["execution_result"]["passed"] is True
    assert result["code_quality_result"]["status"] == "PASS"
    assert result["review"]["status"] == "uncertain"
    # Final verdict MUST be NEEDS_REVIEW
    assert result["final_verdict"] == "NEEDS_REVIEW"


@pytest.mark.asyncio
async def test_workflow_passes_when_all_three_gates_pass(tmp_path: Path):
    """
    Verify integration: When execution passes, AST code quality passes,
    and Semantic Reviewer returns status='pass', final_verdict MUST be PASS.
    """
    def clean_generator(state: AgentState):
        return {
            "tests/test_clean.py": """
from cachetools import LRUCache

def test_cache_op():
    c = LRUCache(maxsize=5)
    c['x'] = 100
    assert c['x'] == 100
"""
        }

    async def passing_reviewer(state: AgentState):
        return {
            "status": "pass",
            "requirement_alignment": 1.0,
            "assertion_strength": 0.95,
            "hallucination_risk": 0.0,
            "confidence": 0.95,
            "reason": "High quality test that accurately verifies SUT behavior.",
        }

    tools = AgentToolRegistry()
    async def mock_run_tests(workspace, command, framework, task_id=None):
        return {"passed": True, "exit_code": 0, "stdout": "1 passed", "stderr": ""}

    tools.register("run_tests", mock_run_tests)

    workflow = AgenticTestWorkflow(
        generator=clean_generator,
        reviewer=passing_reviewer,
        tool_registry=tools,
    )

    result = await workflow.run({
        "requirement": "Verify LRU cache basic key storage",
        "workspace": str(tmp_path),
        "target_entrypoint": "cachetools.LRUCache",
    })

    assert result["execution_result"]["passed"] is True
    assert result["code_quality_result"]["status"] == "PASS"
    assert result["review"]["status"] == "pass"
    # Final verdict MUST be PASS
    assert result["final_verdict"] == "PASS"



