"""Unit tests for Stage 5.5 Claim-to-Evidence Binding and Citation Verification."""

import pytest
from testteller.core.evidence.catalog import EvidenceCatalog2
from testteller.core.evidence.models import EvidenceRecord, TrustLevel
from testteller.quality_gate.claim_binding import ClaimEvidenceBinder
from testteller.quality_gate.code_models import ClaimItem


@pytest.mark.unit
def test_claim_binding_supported_with_provenance():
    """Supported claim binds to evidence record and populates complete provenance chain."""
    catalog = EvidenceCatalog2()
    ev = EvidenceRecord(
        evidence_id="EV-API-LOGIN",
        kind="api_endpoint",
        value="POST /api/v1/login",
        source_id="SRC-LOGIN-1",
        source_path="api/auth.py",
        source_chunk_id="CHK-LOGIN-1",
        commit_sha="0842b24",
        content_hash="h_login",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    catalog.add_record(ev)

    claims = [
        ClaimItem(
            claim_id="C-001",
            kind="api_endpoint",
            value="POST /api/v1/login",
            file_path="tests/test_auth.py",
            line_number=15,
        )
    ]

    res = ClaimEvidenceBinder.bind(
        claims=claims,
        catalog=catalog,
        claimed_citations=["EV-API-LOGIN"],
        target_entrypoint="api.auth",
    )

    assert res.grounded_claim_rate == 1.0
    assert res.citation_accuracy == 1.0
    assert res.has_blocking_violations is False
    assert len(res.bindings) == 1

    b = res.bindings[0]
    assert b.status == "SUPPORTED"
    assert b.evidence_ids == ["EV-API-LOGIN"]
    assert b.provenance_chain["commit_sha"] == "0842b24"
    assert b.provenance_chain["source_chunk_id"] == "CHK-LOGIN-1"
    assert b.provenance_chain["source_path"] == "api/auth.py"


@pytest.mark.unit
def test_claim_binding_unsupported_detection():
    """Unsupported claim in a known domain flags as UNSUPPORTED and creates violation."""
    catalog = EvidenceCatalog2()
    # Catalog has endpoints, but not /magic/delete
    catalog.add_record(
        EvidenceRecord(
            evidence_id="EV-API-1",
            kind="api_endpoint",
            value="GET /api/v1/users",
            source_id="s1",
            source_path="users.py",
            source_chunk_id="c1",
            content_hash="h1",
            extractor="openapi_extractor",
        )
    )

    claims = [
        ClaimItem(
            claim_id="C-002",
            kind="api_endpoint",
            value="POST /api/v1/magic/delete",
            file_path="tests/test_magic.py",
            line_number=20,
        )
    ]

    res = ClaimEvidenceBinder.bind(claims=claims, catalog=catalog)

    assert res.grounded_claim_rate == 0.0
    assert res.has_blocking_violations is True
    assert len(res.unsupported_claims) == 1
    assert len(res.violations) == 1
    assert res.violations[0].code == "UNSUPPORTED_API_ENDPOINT"


@pytest.mark.unit
def test_claim_binding_unknown_when_domain_absent():
    """Claim for domain with no catalog evidence returns UNKNOWN without hard error."""
    catalog = EvidenceCatalog2()
    # Catalog has no UI selector domain knowledge at all

    claims = [
        ClaimItem(
            claim_id="C-003",
            kind="ui_selector",
            value="#submit-button",
            file_path="tests/test_ui.py",
            line_number=10,
        )
    ]

    res = ClaimEvidenceBinder.bind(claims=claims, catalog=catalog)

    assert res.has_blocking_violations is False
    assert len(res.unknown_claims) == 1
    assert res.unknown_claims[0].status == "UNKNOWN"


@pytest.mark.unit
def test_claim_binding_citation_accuracy():
    """Citation accuracy drops if LLM claims citation IDs not matching claims."""
    catalog = EvidenceCatalog2()
    catalog.add_record(
        EvidenceRecord(
            evidence_id="EV-REAL-1",
            kind="target_symbol",
            value="OrderService.create",
            source_id="s1",
            source_path="order.py",
            source_chunk_id="c1",
            content_hash="h1",
            extractor="ast_extractor",
        )
    )

    claims = [
        ClaimItem(
            claim_id="C-004",
            kind="target_symbol",
            value="OrderService.create",
            file_path="tests/test_order.py",
            line_number=5,
        )
    ]

    # LLM claimed EV-REAL-1 (valid) and EV-FAKE-999 (fabricated)
    res = ClaimEvidenceBinder.bind(
        claims=claims,
        catalog=catalog,
        claimed_citations=["EV-REAL-1", "EV-FAKE-999"],
    )

    assert res.grounded_claim_rate == 1.0
    # 1 valid citation out of 2 claimed -> 50% citation accuracy
    assert res.citation_accuracy == 0.5


@pytest.mark.unit
def test_claim_binding_t4_unverified_strictly_rejected():
    """T4_UNVERIFIED evidence record cannot support a factual claim and generates error violation."""
    catalog = EvidenceCatalog2()
    t4_ev = EvidenceRecord(
        evidence_id="EV-T4-LOGIN",
        kind="api_endpoint",
        value="POST /api/v1/auth/login",
        source_id="s_llm",
        source_path="llm_inference.txt",
        source_chunk_id="c_llm",
        commit_sha="any_commit",
        extractor="llm_inference",
        trust_level=TrustLevel.T4_UNVERIFIED,
    )
    catalog.add_record(t4_ev)

    claims = [
        ClaimItem(
            claim_id="C-T4-01",
            kind="api_endpoint",
            value="POST /api/v1/auth/login",
            file_path="tests/test_auth.py",
            line_number=10,
        )
    ]

    res = ClaimEvidenceBinder.bind(claims=claims, catalog=catalog)
    assert res.grounded_claim_rate == 0.0
    assert len(res.unsupported_claims) == 1
    assert res.bindings[0].status == "UNSUPPORTED"
    assert res.bindings[0].citation_valid is False
    assert res.has_blocking_violations is True
    assert any("T4_UNVERIFIED" in v.message for v in res.violations)


@pytest.mark.unit
def test_claim_binding_t4_citation_rejected():
    """Citation pointing to a T4_UNVERIFIED record is rejected, lowering citation accuracy."""
    catalog = EvidenceCatalog2()
    real_ev = EvidenceRecord(
        evidence_id="EV-REAL-AUTH",
        kind="api_endpoint",
        value="POST /api/v1/auth/token",
        source_id="s_real",
        source_path="auth.py",
        source_chunk_id="c_real",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    t4_ev = EvidenceRecord(
        evidence_id="EV-T4-DOC",
        kind="api_endpoint",
        value="POST /api/v1/auth/token",
        source_id="s_t4",
        source_path="t4.txt",
        source_chunk_id="c_t4",
        extractor="llm_inference",
        trust_level=TrustLevel.T4_UNVERIFIED,
    )
    catalog.add_record(real_ev)
    catalog.add_record(t4_ev)

    claims = [
        ClaimItem(
            claim_id="C-005",
            kind="api_endpoint",
            value="POST /api/v1/auth/token",
            file_path="tests/test_token.py",
        )
    ]

    # Claim points to T4 citation
    res = ClaimEvidenceBinder.bind(
        claims=claims,
        catalog=catalog,
        claimed_citations=["EV-T4-DOC"],
    )

    # The claim itself matches EV-REAL-AUTH (T0) so grounded_claim_rate is 1.0, but T4 citation is invalid
    assert res.grounded_claim_rate == 1.0
    assert res.citation_accuracy == 0.0

