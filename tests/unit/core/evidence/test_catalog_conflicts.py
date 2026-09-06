"""Unit tests for Stage 5.3 Evidence Catalog 2.0 and Conflict Resolution."""

import pytest
from testteller.core.evidence.models import EvidenceRecord, TrustLevel
from testteller.core.evidence.catalog import EvidenceCatalog2
from testteller.core.evidence.conflicts import ConflictResolver
from testteller.core.evidence.catalog_builder import EvidenceCatalogBuilder
from testteller.core.retrieval.models import RetrievalItem


@pytest.mark.unit
def test_evidence_catalog2_matching_and_legacy_bridge():
    """EvidenceCatalog2 indexes records and matches templates/symbols accurately."""
    catalog = EvidenceCatalog2()
    r1 = EvidenceRecord(
        evidence_id="EV-1",
        kind="api_endpoint",
        value="GET /api/v1/users/{id}",
        source_id="s1",
        source_path="src/api.py",
        source_chunk_id="c1",
        content_hash="h1",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    r2 = EvidenceRecord(
        evidence_id="EV-2",
        kind="target_symbol",
        value="services.order.OrderService",
        source_id="s2",
        source_path="src/service.py",
        source_chunk_id="c2",
        content_hash="h2",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    catalog.add_records([r1, r2])

    assert catalog.has_domain("api_endpoint")
    assert catalog.has_domain("target_symbol")
    assert not catalog.has_domain("ui_selector")

    # Exact and template matching
    assert catalog.find_match("api_endpoint", "GET /api/v1/users/42") == r1
    assert catalog.find_match("api_endpoint", "POST /api/v1/users/42") is None

    # Symbol suffix matching
    assert catalog.find_match("target_symbol", "OrderService") == r2
    assert catalog.find_match("target_symbol", "services.order.OrderService") == r2

    # Legacy conversion bridge
    legacy = catalog.to_legacy_catalog()
    assert len(legacy.get_items()) == 2
    roundtrip = EvidenceCatalog2.from_legacy_catalog(legacy)
    assert len(roundtrip.all_records()) == 2


@pytest.mark.unit
def test_conflict_resolution_authority_hierarchy():
    """Source AST / OpenAPI must supersede docs on conflicting endpoint specifications."""
    ev_openapi = EvidenceRecord(
        evidence_id="EV-OPENAPI-1",
        kind="api_endpoint",
        value="POST /api/v2/users",
        source_id="s_api",
        source_path="openapi.yaml",
        source_chunk_id="c_api",
        content_hash="h_api",
        extractor="openapi_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    ev_doc = EvidenceRecord(
        evidence_id="EV-DOC-1",
        kind="api_endpoint",
        value="POST /api/v1/users",
        source_id="s_doc",
        source_path="README.md",
        source_chunk_id="c_doc",
        content_hash="h_doc",
        extractor="doc_extractor",
        trust_level=TrustLevel.T2_SUPPORTING,
    )

    resolver = ConflictResolver()
    retained, conflicts = resolver.detect_and_resolve([ev_openapi, ev_doc])

    assert len(conflicts) == 1
    assert conflicts[0].severity == "warning"
    assert conflicts[0].resolved_evidence_id == "EV-OPENAPI-1"
    assert len(retained) == 1
    assert retained[0].evidence_id == "EV-OPENAPI-1"


@pytest.mark.unit
def test_conflict_resolution_pinned_commit_precedence():
    """Pinned commit evidence must strictly supersede stale commit evidence."""
    ev_stale = EvidenceRecord(
        evidence_id="EV-STALE",
        kind="api_endpoint",
        value="POST /v1/checkout",
        source_id="s_stale",
        source_path="checkout.py",
        source_chunk_id="c_stale",
        commit_sha="commit_old_111",
        content_hash="h_stale",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    ev_pinned = EvidenceRecord(
        evidence_id="EV-PINNED",
        kind="api_endpoint",
        value="POST /v2/checkout",
        source_id="s_pinned",
        source_path="checkout.py",
        source_chunk_id="c_pinned",
        commit_sha="commit_pinned_222",
        content_hash="h_pinned",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )

    resolver = ConflictResolver(pinned_commit="commit_pinned_222")
    retained, conflicts = resolver.detect_and_resolve([ev_stale, ev_pinned])

    assert len(conflicts) == 1
    assert conflicts[0].resolved_evidence_id == "EV-PINNED"
    assert retained[0].evidence_id == "EV-PINNED"


@pytest.mark.unit
def test_blocking_conflict_triggers_fail_closed():
    """Unresolvable conflict between two equal sources on same commit flags as blocking."""
    ev1 = EvidenceRecord(
        evidence_id="EV-AST-1",
        kind="api_endpoint",
        value="POST /api/v1/auth",
        source_id="s1",
        source_path="routes_a.py",
        source_chunk_id="c1",
        commit_sha="commit_same",
        content_hash="h1",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    ev2 = EvidenceRecord(
        evidence_id="EV-AST-2",
        kind="api_endpoint",
        value="POST /api/v2/auth",
        source_id="s2",
        source_path="routes_b.py",
        source_chunk_id="c2",
        commit_sha="commit_same",
        content_hash="h2",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )

    resolver = ConflictResolver(pinned_commit="commit_same")
    retained, conflicts = resolver.detect_and_resolve([ev1, ev2])

    assert len(conflicts) == 1
    assert conflicts[0].severity == "blocking"
    assert conflicts[0].resolved_evidence_id is None


@pytest.mark.unit
def test_evidence_catalog_builder_assembly():
    """EvidenceCatalogBuilder creates bundle with provenance and coverage."""
    builder = EvidenceCatalogBuilder(pinned_commit="0842b24")

    ev_item = EvidenceRecord(
        evidence_id="EV-TEST-1",
        kind="target_symbol",
        value="AuthService.login",
        source_id="SRC-1",
        source_path="auth.py",
        source_chunk_id="CHK-1",
        commit_sha="0842b24",
        content_hash="h_auth",
        extractor="ast_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )

    bundle = builder.build_bundle(
        extracted_records=[ev_item],
    )

    assert bundle.provenance_complete is True
    assert len(bundle.evidence) == 1
    assert len(bundle.conflicts) == 0
