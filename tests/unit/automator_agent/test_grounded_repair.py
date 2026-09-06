"""Unit tests for Stage 5.6 Grounded Generation and Evidence-Constrained Self-Repair."""

import pytest
from testteller.core.evidence.catalog import EvidenceCatalog2
from testteller.core.evidence.models import EvidenceRecord, TrustLevel
from testteller.automator_agent.repair_planner import (
    RepairGroundingPlanner,
    RepairPlan,
    RepairChange,
)


@pytest.mark.unit
def test_repair_query_formulation_from_traceback():
    """Formulate targeted grounding queries from execution failure logs."""
    log = """
Traceback (most recent call last):
  File "test_user.py", line 12, in test_create_user
    client.post("http://localhost:8000/api/v1/user/add")
  404 Not Found: for url: /api/v1/user/add
AttributeError: 'UserService' object has no attribute 'create_account'
"""
    queries = RepairGroundingPlanner.formulate_repair_queries(log)
    kinds = [q.kind for q in queries]

    assert "target_symbol" in kinds
    assert "api_endpoint" in kinds

    sym_query = next(q for q in queries if q.kind == "target_symbol")
    assert "UserService" in sym_query.exact_terms


@pytest.mark.unit
def test_repair_plan_rejected_without_evidence_for_expectation_change():
    """Expectation change without authoritative evidence must be strictly rejected."""
    catalog = EvidenceCatalog2()

    # Plan proposes altering expected status code from 200 to 201 without evidence
    plan = RepairPlan(
        root_cause="AssertionError: assert res.status_code == 200 (actual: 201)",
        proposed_changes=[
            RepairChange(
                change_type="alter_expectation",
                target="res.status_code == 200",
                description="Change expected status to 201",
            )
        ],
        expectation_changes=["status_code 200 -> 201"],
        required_evidence_ids=[],  # NO evidence!
    )

    validated = RepairGroundingPlanner.validate_repair_plan(plan, catalog)
    assert validated.allow_repair is False
    assert "Rejected expectation change" in (validated.rejection_reason or "")


@pytest.mark.unit
def test_repair_plan_accepted_with_authoritative_evidence():
    """Expectation change backed by verified authoritative evidence is accepted."""
    catalog = EvidenceCatalog2()
    ev = EvidenceRecord(
        evidence_id="EV-CONTRACT-201",
        kind="behavior_contract",
        value="POST /api/users -> 201",
        source_id="s_openapi",
        source_path="openapi.yaml",
        source_chunk_id="c_openapi",
        content_hash="h_201",
        extractor="openapi_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    catalog.add_record(ev)

    plan = RepairPlan(
        root_cause="AssertionError: expected 200 got 201",
        proposed_changes=[
            RepairChange(
                change_type="alter_expectation",
                target="status_code",
                description="Update expected status to 201 per OpenAPI",
                evidence_id="EV-CONTRACT-201",
            )
        ],
        expectation_changes=["status_code 200 -> 201"],
        required_evidence_ids=["EV-CONTRACT-201"],
    )

    validated = RepairGroundingPlanner.validate_repair_plan(plan, catalog)
    assert validated.allow_repair is True
    assert validated.rejection_reason is None
