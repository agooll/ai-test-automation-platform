"""Unit tests for Stage 5.7 LangGraph Grounding Nodes and Relational Evidence Persistence."""

import asyncio
import tempfile
import pytest
from pathlib import Path
from testteller.agent_runtime.graph import AgenticTestWorkflow
from testteller.agent_runtime.grounding_nodes import (
    grounding_plan_node,
    evidence_build_node,
    claim_bind_node,
)
from testteller.core.evidence.models import (
    EvidenceRecord,
    SourceChunk,
    SourceManifest,
    TrustLevel,
)
from testteller.core.evidence.repository import EvidenceRepository
from testteller.quality_gate.claim_binding import ClaimEvidenceBinding


@pytest.mark.unit
def test_grounding_plan_node_execution():
    """grounding_plan_node produces structured plan and records trace event."""
    state = {
        "requirement": "Verify POST /api/v1/users creates user with email and returns 201.",
        "target_entrypoint": "api.users",
        "trace": [],
    }
    result = asyncio.run(grounding_plan_node(state))

    assert "grounding_query_plan" in result
    plan = result["grounding_query_plan"]
    assert len(plan["queries"]) >= 2
    assert any(t.get("type") == "GROUNDING_PLAN_COMPLETED" for t in result["trace"])


@pytest.mark.unit
def test_evidence_build_node_with_workspace_ast():
    """evidence_build_node extracts AST facts from workspace and builds EvidenceBundle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        py_file = ws / "routes.py"
        py_file.write_text(
            "@app.get('/api/health')\ndef health(): return {'status': 'ok'}\n",
            encoding="utf-8",
        )

        state = {
            "workspace": str(ws),
            "requirement": "Test health endpoint",
            "pinned_commit": "0842b24",
            "trace": [],
        }

        result = asyncio.run(evidence_build_node(state))
        assert "evidence_catalog" in result
        evs = result["evidence_catalog"]
        assert len(evs) >= 1
        assert any(e.value == "GET /api/health" for e in evs)
        assert result["provenance_completeness"] is True


@pytest.mark.unit
def test_claim_bind_node_with_generated_code():
    """claim_bind_node binds generated code claims to catalog evidence."""
    ev_cls = EvidenceRecord(
        evidence_id="EV-TEST-CLS",
        kind="target_symbol",
        value="order.OrderService",
        source_id="s1",
        source_path="order.py",
        source_chunk_id="c1",
        content_hash="h1",
        extractor="ast_extractor",
    )
    ev_short = EvidenceRecord(
        evidence_id="EV-TEST-SHORT",
        kind="target_symbol",
        value="OrderService",
        source_id="s1",
        source_path="order.py",
        source_chunk_id="c1",
        content_hash="h1",
        extractor="ast_extractor",
    )
    ev_method = EvidenceRecord(
        evidence_id="EV-TEST-ORDER",
        kind="target_symbol",
        value="OrderService.place_order",
        source_id="s1",
        source_path="order.py",
        source_chunk_id="c1",
        content_hash="h1",
        extractor="ast_extractor",
    )
    code = """
from order import OrderService

def test_order():
    svc = OrderService()
    svc.place_order()
"""
    state = {
        "generated_files": {"tests/test_order.py": code},
        "target_entrypoint": "order.OrderService",
        "evidence_catalog": [ev_cls, ev_short, ev_method],
        "trace": [],
    }

    result = asyncio.run(claim_bind_node(state))
    assert "claim_bindings" in result
    assert result["grounded_claim_rate"] == 1.0
    assert "grounding_manifest" in result
    assert any(t.get("type") == "CLAIM_BINDING_COMPLETED" for t in result["trace"])


@pytest.mark.unit
def test_evidence_repository_provenance_trail():
    """EvidenceRepository persists evidence graph and returns complete provenance trail."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "evidence_audit.sqlite3")
        repo = EvidenceRepository(db_path)

        manifest = SourceManifest(
            source_id="SRC-USER-PY",
            repository="testteller",
            commit_sha="0842b24",
            path="src/users.py",
            file_type="python",
            content_hash="h_src",
        )
        chunk = SourceChunk(
            chunk_id="CHK-USER-1",
            source_id="SRC-USER-PY",
            text="@app.get('/users')\ndef get_users(): pass\n",
            line_start=10,
            line_end=12,
            content_hash="h_chk",
        )
        ev = EvidenceRecord(
            evidence_id="EV-GET-USERS",
            kind="api_endpoint",
            value="GET /users",
            source_id="SRC-USER-PY",
            source_path="src/users.py",
            source_chunk_id="CHK-USER-1",
            line_start=10,
            line_end=12,
            commit_sha="0842b24",
            content_hash="h_chk",
            extractor="ast_extractor",
            trust_level=TrustLevel.T0_AUTHORITATIVE,
        )
        binding = ClaimEvidenceBinding(
            claim_id="CLM-01",
            kind="api_endpoint",
            value="GET /users",
            status="SUPPORTED",
            evidence_ids=["EV-GET-USERS"],
            source_file="tests/test_users.py",
            line_number=5,
        )

        repo.save_manifest(manifest)
        repo.save_chunk(chunk)
        repo.save_evidence_record(ev)
        repo.save_claim_binding(binding)

        trail = repo.get_provenance_trail("EV-GET-USERS")
        assert trail is not None
        assert trail["evidence_id"] == "EV-GET-USERS"
        assert trail["source_path"] == "src/users.py"
        assert trail["commit_sha"] == "0842b24"
        assert trail["line_start"] == 10
        assert trail["line_end"] == 12
        assert trail["chunk_id"] == "CHK-USER-1"


@pytest.mark.unit
def test_evidence_build_node_disambiguates_target_repo():
    """evidence_build_node scans target_repo rather than execution workspace when specified."""
    with tempfile.TemporaryDirectory() as target_dir, tempfile.TemporaryDirectory() as ws_dir:
        repo_path = Path(target_dir)
        py_file = repo_path / "models.py"
        py_file.write_text("class TargetModel:\n    pass\n", encoding="utf-8")

        state = {
            "target_repo": str(repo_path),
            "workspace": str(ws_dir),
            "requirement": "Verify TargetModel",
            "pinned_commit": "commit_abc123",
            "trace": [],
        }

        result = asyncio.run(evidence_build_node(state))
        assert "evidence_catalog" in result
        evs = result["evidence_catalog"]
        assert any(e.value == "TargetModel" for e in evs)
        model_ev = next(e for e in evs if e.value == "TargetModel")
        assert model_ev.commit_sha == "commit_abc123"


@pytest.mark.unit
def test_claim_bind_node_extracts_inline_citations():
    """claim_bind_node extracts # @cite annotations and computes citation accuracy."""
    ev = EvidenceRecord(
        evidence_id="EV-AUTH-VERIFY",
        kind="target_symbol",
        value="auth.TokenService",
        source_id="s1",
        source_path="auth.py",
        source_chunk_id="c1",
        extractor="ast_extractor",
    )
    code = """
# @cite EV-AUTH-VERIFY
def test_token_valid():
    from auth import TokenService
    TokenService.verify()
"""
    state = {
        "generated_files": {"tests/test_token.py": code},
        "target_entrypoint": "auth.TokenService",
        "evidence_catalog": [ev],
        "trace": [],
    }

    result = asyncio.run(claim_bind_node(state))
    assert result["citation_accuracy"] == 1.0
    assert result["grounded_claim_rate"] == 1.0


@pytest.mark.unit
def test_review_node_fail_closed_on_core_unknowns():
    """_review_node demotes final verdict to NEEDS_REVIEW if core business fact claim is UNKNOWN."""
    workflow = AgenticTestWorkflow(
        planner=lambda s: {},
        generator=lambda s: {},
        repairer=lambda s: {},
        reviewer=lambda s: {"status": "pass"},
    )
    state = {
        "execution_result": {"passed": True, "exit_code": 0},
        "code_quality_result": {"status": "PASS"},
        "grounding_coverage_score": 0.95,
        "provenance_completeness": True,
        "grounded_claim_rate": 0.96,
        "unknown_claims": [
            {"kind": "api_endpoint", "value": "POST /api/v1/unknown_route", "status": "UNKNOWN"}
        ],
        "unsupported_claims": [],
        "trace": [],
    }
    new_state = asyncio.run(workflow._review_node(state))
    assert new_state["final_verdict"] == "NEEDS_REVIEW"


@pytest.mark.unit
def test_review_node_fail_closed_on_low_coverage():
    """_review_node demotes final verdict to NEEDS_REVIEW if grounding_coverage_score < 0.80."""
    workflow = AgenticTestWorkflow(
        planner=lambda s: {},
        generator=lambda s: {},
        repairer=lambda s: {},
        reviewer=lambda s: {"status": "pass"},
    )
    state = {
        "execution_result": {"passed": True, "exit_code": 0},
        "code_quality_result": {"status": "PASS"},
        "grounding_coverage_score": 0.70,  # Below 0.80 threshold
        "provenance_completeness": True,
        "grounded_claim_rate": 0.98,
        "unknown_claims": [],
        "unsupported_claims": [],
        "trace": [],
    }
    new_state = asyncio.run(workflow._review_node(state))
    assert new_state["final_verdict"] == "NEEDS_REVIEW"


@pytest.mark.unit
def test_persist_node_relational_evidence_persistence():
    """_persist_node saves evidence_catalog and claim_bindings to SQLite."""
    workflow = AgenticTestWorkflow(
        planner=lambda s: {},
        generator=lambda s: {},
        repairer=lambda s: {},
        reviewer=lambda s: {"status": "pass"},
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "evidence.sqlite")
        ev = EvidenceRecord(
            evidence_id="EV-PERSIST-1",
            kind="api_endpoint",
            value="GET /health",
            source_id="s1",
            source_path="health.py",
            source_chunk_id="c1",
            extractor="openapi_extractor",
        )
        binding = ClaimEvidenceBinding(
            claim_id="CLM-P1",
            kind="api_endpoint",
            value="GET /health",
            status="SUPPORTED",
            evidence_ids=["EV-PERSIST-1"],
            source_file="tests/test_h.py",
        )
        state = {
            "evidence_db_path": db_path,
            "evidence_catalog": [ev],
            "claim_bindings": [binding],
            "trace": [],
        }
        asyncio.run(workflow._persist_node(state))

        repo = EvidenceRepository(db_path)
        trail = repo.get_provenance_trail("EV-PERSIST-1")
        assert trail is not None
        assert trail["evidence_id"] == "EV-PERSIST-1"
        assert trail["source_path"] == "health.py"
        assert trail["chunk_id"] == "c1"


