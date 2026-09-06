"""Unit tests for Stage 5.4 Grounding Query Planner and Hybrid Retrieval 2.0."""

import asyncio
import tempfile
import pytest
from unittest.mock import MagicMock
from testteller.core.retrieval.query_planner import GroundingQueryPlanner
from testteller.core.retrieval.result_fusion import fuse_results
from testteller.core.retrieval.hybrid_retriever import HybridRetriever
from testteller.core.retrieval.local_index import LocalIndex
from testteller.core.retrieval.models import RetrievalItem


@pytest.mark.unit
def test_query_planner_decomposition():
    """GroundingQueryPlanner decomposes requirements into structured factual sub-queries."""
    planner = GroundingQueryPlanner()
    req = (
        "Verify admin user can POST /api/v1/users with email and password. "
        "Successful creation returns 201. Unauthorized request without token returns 401. "
        "Depends on JWT_SECRET configuration."
    )
    plan = planner.plan(requirement_text=req, target_entrypoint="auth.UserService")

    assert plan.target_entrypoint == "auth.UserService"
    kinds = [q.kind for q in plan.queries]

    assert "target_symbol" in kinds
    assert "api_endpoint" in kinds
    assert "model_field" in kinds
    assert "auth_pattern" in kinds
    assert "behavior_contract" in kinds
    assert "config" in kinds

    ep_query = next(q for q in plan.queries if q.kind == "api_endpoint")
    assert "POST /api/v1/users" in ep_query.exact_terms


@pytest.mark.unit
def test_fuse_results_authority_and_pinned_commit():
    """fuse_results applies authority bonus and favors pinned commit over stale commit."""
    # Item 1: Plain doc on stale commit
    item_doc = RetrievalItem(
        document_id="doc-1",
        chunk_id="chunk-doc",
        source="README.md",
        content="POST /api/v1/users",
        metadata={"type": "document", "commit_sha": "stale_commit_111"},
        vector_rank=1,
    )
    # Item 2: Code chunk on pinned commit
    item_code = RetrievalItem(
        document_id="code-1",
        chunk_id="chunk-code",
        source="src/api.py",
        content="@app.post('/api/v2/users')",
        metadata={"type": "code", "commit_sha": "pinned_commit_222"},
        vector_rank=2,
    )

    fused = fuse_results([item_doc, item_code], [], limit=5, pinned_commit="pinned_commit_222")

    # The code item on pinned commit must be ranked #1
    assert len(fused) == 2
    assert fused[0].chunk_id == "chunk-code"
    assert fused[0].final_rank == 1


@pytest.mark.unit
def test_hybrid_retriever_plan_execution():
    """HybridRetriever.retrieve_plan queries SQLite local index first for exact terms."""
    with tempfile.TemporaryDirectory() as tmpdir:
        index = LocalIndex(tmpdir)
        # Ingest exact route into SQLite index
        doc = '@app.post("/api/v1/login")\ndef login(): pass'
        meta = {
            "source": "api/auth.py",
            "source_id": "SRC-AUTH",
            "commit_sha": "0842b24",
            "line_start": 5,
            "line_end": 7,
            "type": "code",
        }
        index.add_documents([doc], [meta], ["chunk-auth-1"], "test_col")

        mock_vector_store = MagicMock()
        mock_vector_store.query_similar.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]]}

        retriever = HybridRetriever(mock_vector_store, index)
        planner = GroundingQueryPlanner()
        plan = planner.plan("Test POST /api/v1/login returns token")

        results = asyncio.run(
            retriever.retrieve_plan(plan, "test_col", pinned_commit="0842b24")
        )

        assert len(results) >= 1
        assert results[0].chunk_id == "chunk-auth-1"
        assert results[0].source == "api/auth.py"
