"""Unit tests for Stage 5.1 Provenance Foundation and Content-Addressed Identifiers."""

import tempfile
import pytest
from testteller.core.evidence.models import (
    TrustLevel,
    SourceManifest,
    SourceChunk,
    EvidenceRecord,
)
from testteller.core.evidence.ids import (
    compute_source_id,
    compute_chunk_id,
    compute_evidence_id,
    compute_content_hash,
    normalize_evidence_value,
    normalize_relative_path,
)
from testteller.core.evidence.chunking import LineAwareChunker
from testteller.core.evidence.trust import (
    can_support_factual_claim,
    resolve_authority_winner,
)
from testteller.core.retrieval.local_index import LocalIndex
from testteller.core.retrieval.models import QueryAnalysis, QueryIntent


@pytest.mark.unit
def test_deterministic_source_id():
    """source_id must be deterministic and identical for same repo/commit/path."""
    s1 = compute_source_id("my-repo", "0842b24", "src/api/users.py")
    s2 = compute_source_id("my-repo", "0842b24", "src/api/users.py")
    s3 = compute_source_id("my-repo", "0842b24", "src\\api\\users.py")  # Windows slashes
    assert s1 == s2 == s3
    assert len(s1) == 64

    # Changing commit or path must produce different source_id
    diff_commit = compute_source_id("my-repo", "b300d39", "src/api/users.py")
    diff_path = compute_source_id("my-repo", "0842b24", "src/api/orders.py")
    assert s1 != diff_commit
    assert s1 != diff_path


@pytest.mark.unit
def test_deterministic_chunk_id():
    """chunk_id must be tamper-sensitive and deterministic."""
    source_id = compute_source_id("repo", "commit1", "file.py")
    content = "def hello():\n    return 'world'\n"
    c_hash = compute_content_hash(content)

    c1 = compute_chunk_id(source_id, 1, 2, c_hash)
    c2 = compute_chunk_id(source_id, 1, 2, c_hash)
    assert c1 == c2

    # Modified content alters hash and chunk_id
    modified_content = "def hello():\n    return 'universe'\n"
    mod_hash = compute_content_hash(modified_content)
    c3 = compute_chunk_id(source_id, 1, 2, mod_hash)
    assert c1 != c3

    # Modified line range alters chunk_id
    c4 = compute_chunk_id(source_id, 10, 11, c_hash)
    assert c1 != c4


@pytest.mark.unit
def test_deterministic_evidence_id():
    """evidence_id must normalize values and be deterministic."""
    chunk_id = "chunk-12345"
    e1 = compute_evidence_id("api_endpoint", "POST /api/users", chunk_id)
    e2 = compute_evidence_id("api_endpoint", "post /api/users/", chunk_id)
    e3 = compute_evidence_id("api_endpoint", "POST http://localhost:8000/api/users", chunk_id)

    assert e1 == e2 == e3
    assert e1.startswith("EV-api_endpoint-")

    # Different chunk or value produces different ID
    e_diff = compute_evidence_id("api_endpoint", "GET /api/users", chunk_id)
    assert e1 != e_diff


@pytest.mark.unit
def test_line_aware_chunker_text():
    """LineAwareChunker accurately tracks 1-indexed lines and content hashes."""
    text = "\n".join([f"line {i}" for i in range(1, 101)])
    chunker = LineAwareChunker(max_lines_per_chunk=30, overlap_lines=5)
    chunks = chunker.chunk_text(text, source_id="src-001", file_type="text")

    assert len(chunks) > 1
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == 30
    assert chunks[0].source_id == "src-001"
    assert chunks[0].content_hash == compute_content_hash(chunks[0].text)


@pytest.mark.unit
def test_line_aware_chunker_python():
    """Python AST chunking splits along class/function definitions."""
    py_code = (
        "# Header\n"
        "import os\n\n"
        "class UserService:\n"
        "    def create(self):\n"
        "        return True\n\n"
        "def helper():\n"
        "    return 42\n"
    )
    chunker = LineAwareChunker()
    chunks = chunker.chunk_text(py_code, source_id="src-py", file_type="python")

    assert len(chunks) >= 2
    scopes = [c.metadata.get("scope") for c in chunks]
    assert "UserService" in scopes
    assert "helper" in scopes


@pytest.mark.unit
def test_trust_levels_and_authority():
    """TrustLevel ranks and authority checks match Stage 5 hierarchy."""
    assert TrustLevel.T0_AUTHORITATIVE.rank < TrustLevel.T1_STRONG.rank
    assert TrustLevel.T1_STRONG.rank < TrustLevel.T2_SUPPORTING.rank
    assert TrustLevel.T2_SUPPORTING.rank < TrustLevel.T3_WEAK.rank
    assert TrustLevel.T3_WEAK.rank < TrustLevel.T4_UNVERIFIED.rank

    assert can_support_factual_claim(TrustLevel.T0_AUTHORITATIVE) is True
    assert can_support_factual_claim(TrustLevel.T1_STRONG) is True
    assert can_support_factual_claim(TrustLevel.T2_SUPPORTING) is False
    assert can_support_factual_claim(TrustLevel.T4_UNVERIFIED) is False

    # Precedence: Pinned commit wins over stale commit
    ev_stale = EvidenceRecord(
        evidence_id="EV-1",
        kind="api_endpoint",
        value="GET /v1/users",
        source_id="s1",
        source_path="src/v1.py",
        source_chunk_id="c1",
        commit_sha="stale_commit_111",
        content_hash="h1",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    ev_pinned = EvidenceRecord(
        evidence_id="EV-2",
        kind="api_endpoint",
        value="GET /v2/users",
        source_id="s2",
        source_path="src/v2.py",
        source_chunk_id="c2",
        commit_sha="pinned_commit_222",
        content_hash="h2",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )

    winner = resolve_authority_winner(ev_stale, ev_pinned, pinned_commit="pinned_commit_222")
    assert winner == ev_pinned


@pytest.mark.unit
def test_local_index_provenance_roundtrip():
    """LocalIndex stores and retrieves chunk provenance columns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        index = LocalIndex(tmpdir)
        doc = "class PaymentProcessor:\n    def charge(self): pass\n"
        meta = {
            "source": "services/payment.py",
            "source_id": "SRC-PAYMENT-001",
            "commit_sha": "0842b24",
            "line_start": 10,
            "line_end": 12,
            "content_hash": compute_content_hash(doc),
        }
        index.add_documents([doc], [meta], ["chunk-pay-1"], "test_collection")

        # Query exact symbol
        analysis = QueryAnalysis(
            query="PaymentProcessor",
            intent=QueryIntent.FACT_LOOKUP,
            symbols=["PaymentProcessor"],
        )
        res = index.search(analysis, "test_collection")
        assert len(res.items) == 1
        item = res.items[0]
        assert item.metadata.get("source_id") == "SRC-PAYMENT-001"
        assert item.metadata.get("commit_sha") == "0842b24"
        assert item.metadata.get("line_start") == 10
        assert item.metadata.get("line_end") == 12
        assert item.metadata.get("content_hash") == compute_content_hash(doc)
