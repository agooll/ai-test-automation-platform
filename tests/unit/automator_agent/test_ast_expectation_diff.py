"""Unit tests and regressions for ASTExpectationExtractor and expectation diffing."""

import pytest
from testteller.automator_agent.repair_planner import ASTExpectationExtractor
from testteller.core.evidence.models import EvidenceRecord, TrustLevel


@pytest.mark.unit
def test_ast_extract_status_code_comparisons():
    """Extract comparisons against status_code and normalize targets."""
    code = """
def test_endpoint():
    res = client.get("/api/v1/resource")
    assert res.status_code == 200
    assert res.status == 200
"""
    expectations = ASTExpectationExtractor.extract_expectations(code)
    assert "status_code" in expectations
    assert expectations["status_code"] == {"200"}


@pytest.mark.unit
def test_ast_extract_assert_equal_and_unary():
    """Extract unittest.assertEqual and assert not expressions."""
    code = """
def test_case(self):
    self.assertEqual(res.status_code, 201)
    assert not res.is_error
    assert res.is_valid
"""
    expectations = ASTExpectationExtractor.extract_expectations(code)
    assert "status_code" in expectations
    assert "201" in expectations["status_code"]
    assert "*.is_error" in expectations
    assert expectations["*.is_error"] == {"False"}
    assert "*.is_valid" in expectations
    assert expectations["*.is_valid"] == {"True"}


@pytest.mark.unit
def test_ast_extract_pytest_raises_and_assert_raises():
    """Extract exception types from pytest.raises and assertRaises."""
    code = """
def test_errors(self):
    with pytest.raises(ValueError):
        do_something()
    self.assertRaises(TypeError, do_other)
"""
    expectations = ASTExpectationExtractor.extract_expectations(code)
    assert "pytest.raises" in expectations
    assert "ValueError" in expectations["pytest.raises"]
    assert "TypeError" in expectations["pytest.raises"]


@pytest.mark.unit
def test_ast_find_unbacked_expectation_changes_blocked():
    """Modifying expected status_code without evidence is detected as unbacked."""
    old_code = """
def test_api():
    res = client.get("/users")
    assert res.status_code == 200
"""
    new_code = """
def test_api():
    res = client.get("/users")
    assert res.status_code == 404
"""
    unbacked = ASTExpectationExtractor.find_unbacked_expectation_changes(
        before_code=old_code,
        proposed_code=new_code,
        catalog_records=[],  # Empty catalog
    )
    assert len(unbacked) == 1
    assert "status_code" in unbacked[0]
    assert "404" in unbacked[0]


@pytest.mark.unit
def test_ast_find_unbacked_changes_allowed_when_backed():
    """Modifying expected status_code with authoritative evidence is allowed."""
    old_code = """
def test_api():
    res = client.get("/users")
    assert res.status_code == 200
"""
    new_code = """
def test_api():
    res = client.get("/users")
    assert res.status_code == 201
"""
    ev = EvidenceRecord(
        evidence_id="EV-OPENAPI-201",
        kind="behavior_contract",
        value="POST /users -> 201",
        source_id="s1",
        source_path="openapi.yaml",
        source_chunk_id="c1",
        commit_sha="0842b24",
        content_hash="h1",
        extractor="openapi_extractor",
        trust_level=TrustLevel.T0_AUTHORITATIVE,
    )
    unbacked = ASTExpectationExtractor.find_unbacked_expectation_changes(
        before_code=old_code,
        proposed_code=new_code,
        catalog_records=[ev],
    )
    assert len(unbacked) == 0


@pytest.mark.unit
def test_ast_input_data_change_not_flagged_as_expectation_alteration():
    """Changing test input payload while keeping expectations unchanged does not trigger violation."""
    old_code = """
def test_create():
    payload = {"name": "Alice"}
    res = client.post("/users", json=payload)
    assert res.status_code == 201
"""
    new_code = """
def test_create():
    payload = {"name": "Bob", "role": "admin"}
    res = client.post("/users", json=payload)
    assert res.status_code == 201
"""
    unbacked = ASTExpectationExtractor.find_unbacked_expectation_changes(
        before_code=old_code,
        proposed_code=new_code,
        catalog_records=[],
    )
    assert len(unbacked) == 0
