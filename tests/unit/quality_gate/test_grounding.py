"""Unit tests for Stage 4.2: Grounding catalog, symbol extractor, and anti-hallucination validation."""

import ast
from pathlib import Path
import pytest

pytestmark = [pytest.mark.unit]

from testteller.quality_gate.code_models import (
    ClaimItem,
    CodeViolationCode,
    EvidenceItem,
)
from testteller.quality_gate.grounding import (
    CodeClaimExtractor,
    EvidenceCatalog,
    GroundingValidator,
    RepoSymbolExtractor,
)
from testteller.quality_gate.code_gate import AutomationCodeQualityGate


class TestRepoSymbolExtractor:
    """Test AST-based symbol extraction from files, directories, and entrypoints."""

    def test_extract_from_file(self, tmp_path):
        py_file = tmp_path / "sample_module.py"
        py_file.write_text(
            """
__all__ = ["Widget", "create_widget"]

class Widget:
    def __init__(self, name: str):
        self.name = name

    def render(self) -> str:
        return f"<div>{self.name}</div>"

def create_widget(name: str) -> Widget:
    return Widget(name)

def _internal_helper():
    pass
""",
            encoding="utf-8",
        )

        items = RepoSymbolExtractor.extract_from_file(py_file, module_prefix="my_app")
        values = {item.value for item in items}

        assert "my_app.Widget" in values
        assert "Widget" in values
        assert "my_app.Widget.render" in values
        assert "my_app.create_widget" in values
        assert "create_widget" in values
        assert all(item.kind == "target_symbol" for item in items)
        assert all(item.confidence == 1.0 for item in items)

    def test_extract_from_cachetools_project(self):
        cachetools_path = Path("evals/projects/cache/cachetools")
        if not cachetools_path.exists():
            pytest.skip("evals/projects/cache/cachetools not present on disk")

        items = RepoSymbolExtractor.extract_from_entrypoint(
            target_entrypoint="cachetools.LRUCache",
            repo_root=cachetools_path,
        )
        values = {item.value for item in items}

        assert "cachetools.LRUCache" in values
        assert "LRUCache" in values
        assert any("Cache" in v for v in values)


class TestCodeClaimExtractor:
    """Test AST visitor extracting API, UI, model field, and target symbol claims."""

    def test_extract_api_endpoint_and_payload_claims(self):
        code = """
import requests

def test_api_calls():
    resp1 = requests.get("https://api.example.com/api/v1/users?page=1")
    assert resp1.status_code == 200

    resp2 = requests.post("/api/auth/login", json={"email": "test@example.com", "password": "secret"})
    assert resp2.status_code == 200
"""
        tree = ast.parse(code)
        extractor = CodeClaimExtractor(file_path="tests/test_api.py")
        extractor.visit(tree)

        api_claims = [c for c in extractor.claims if c.kind == "api_endpoint"]
        assert len(api_claims) == 2
        assert api_claims[0].value == "GET /api/v1/users"
        assert api_claims[1].value == "POST /api/auth/login"

        field_claims = [c for c in extractor.claims if c.kind == "model_field"]
        assert len(field_claims) == 2
        field_names = {f.value for f in field_claims}
        assert field_names == {"email", "password"}

    def test_extract_ui_selector_claims(self):
        code = """
def test_ui(page):
    page.locator("[data-testid='submit-button']").click()
    page.click("#login-btn")
    page.fill("input[name='username']", "admin")
"""
        tree = ast.parse(code)
        extractor = CodeClaimExtractor(file_path="tests/test_ui.py")
        extractor.visit(tree)

        ui_claims = [c for c in extractor.claims if c.kind == "ui_selector"]
        assert len(ui_claims) == 3
        selectors = {c.value for c in ui_claims}
        assert "[data-testid='submit-button']" in selectors
        assert "#login-btn" in selectors
        assert "input[name='username']" in selectors

    def test_extract_target_symbol_claims(self):
        code = """
from cachetools import LRUCache, NonExistentClass

def test_cache():
    cache = LRUCache(maxsize=10)
    assert cache.maxsize == 10
"""
        tree = ast.parse(code)
        extractor = CodeClaimExtractor(
            file_path="tests/test_cache.py",
            target_entrypoint="cachetools.LRUCache",
        )
        extractor.visit(tree)

        target_claims = [c for c in extractor.claims if c.kind == "target_symbol"]
        values = {c.value for c in target_claims}
        assert "cachetools.LRUCache" in values
        assert "LRUCache" in values
        assert "cachetools.NonExistentClass" in values
        assert "NonExistentClass" in values


class TestEvidenceCatalog:
    """Test evidence index, domain check, and normalization."""

    def test_catalog_domain_and_matching(self):
        catalog = EvidenceCatalog(
            [
                EvidenceItem(
                    evidence_id="E-001",
                    kind="api_endpoint",
                    value="POST /api/auth/login",
                    source="src/api.py",
                ),
                EvidenceItem(
                    evidence_id="E-002",
                    kind="api_endpoint",
                    value="GET /api/users/{id}",
                    source="src/api.py",
                ),
                EvidenceItem(
                    evidence_id="E-003",
                    kind="target_symbol",
                    value="cachetools.LRUCache",
                    source="src/cache.py",
                ),
            ]
        )

        assert catalog.has_domain("api_endpoint") is True
        assert catalog.has_domain("target_symbol") is True
        assert catalog.has_domain("ui_selector") is False

        # Exact match with different formatting
        claim1 = ClaimItem(
            claim_id="C-1",
            kind="api_endpoint",
            value="post /api/auth/login/",
            file_path="test.py",
        )
        match1 = catalog.find_match(claim1)
        assert match1 is not None
        assert match1.evidence_id == "E-001"

        # Parameterized path match
        claim2 = ClaimItem(
            claim_id="C-2",
            kind="api_endpoint",
            value="GET /api/users/42",
            file_path="test.py",
        )
        match2 = catalog.find_match(claim2)
        assert match2 is not None
        assert match2.evidence_id == "E-002"

        # Short symbol match
        claim3 = ClaimItem(
            claim_id="C-3",
            kind="target_symbol",
            value="LRUCache",
            file_path="test.py",
        )
        match3 = catalog.find_match(claim3)
        assert match3 is not None
        assert match3.evidence_id == "E-003"


class TestGroundingValidator:
    """Test 3-state validation logic: SUPPORTED, UNSUPPORTED, UNKNOWN."""

    def test_three_state_validation(self):
        catalog = EvidenceCatalog(
            [
                EvidenceItem(
                    evidence_id="E-001",
                    kind="api_endpoint",
                    value="POST /api/auth/login",
                    source="src/api.py",
                ),
            ]
        )

        claims = [
            # 1. Supported: matches E-001
            ClaimItem(
                claim_id="C-1",
                kind="api_endpoint",
                value="POST /api/auth/login",
                file_path="test.py",
                line_number=10,
            ),
            # 2. Unsupported: catalog has api_endpoint domain, but this endpoint is hallucinated
            ClaimItem(
                claim_id="C-2",
                kind="api_endpoint",
                value="POST /api/auth/signin",
                file_path="test.py",
                line_number=15,
            ),
            # 3. Unknown: catalog has NO ui_selector domain, do not falsely reject
            ClaimItem(
                claim_id="C-3",
                kind="ui_selector",
                value="[data-testid='submit']",
                file_path="test.py",
                line_number=20,
            ),
        ]

        violations, findings, score = GroundingValidator.validate(claims, catalog)

        # C-1 should be SUPPORTED
        assert claims[0].status == "SUPPORTED"
        assert claims[0].matched_evidence_id == "E-001"

        # C-2 should be UNSUPPORTED and produce a CodeViolation
        assert claims[1].status == "UNSUPPORTED"
        assert len(violations) == 1
        assert violations[0].code == CodeViolationCode.UNSUPPORTED_API_ENDPOINT
        assert violations[0].line_number == 15
        assert "POST /api/auth/signin" in violations[0].message
        assert "POST /api/auth/login" in violations[0].suggestion

        # C-3 should be UNKNOWN (no violation created)
        assert claims[2].status == "UNKNOWN"

        # Score calculation: 1 out of 3 unsupported -> 1.0 - 1/3 = 0.6667
        assert score == pytest.approx(0.6667, abs=0.001)


@pytest.mark.asyncio
class TestAutomationCodeGateGroundingIntegration:
    """Test end-to-end integration between AutomationCodeQualityGate and Grounding."""

    async def test_gate_rejects_unsupported_api_endpoint(self):
        catalog = EvidenceCatalog(
            [
                EvidenceItem(
                    evidence_id="E-API-1",
                    kind="api_endpoint",
                    value="POST /api/auth/login",
                    source="src/auth.py",
                ),
            ]
        )

        test_code = """
import requests

def test_login():
    resp = requests.post("/api/auth/signin", json={"username": "admin"})
    assert resp.status_code == 200
"""
        gate = AutomationCodeQualityGate()
        res = await gate.evaluate(
            generated_files={"tests/test_auth.py": test_code},
            evidence_catalog=catalog,
        )

        assert res.status == "REJECTED"
        assert res.allow_final_pass is False
        assert any(v.code == CodeViolationCode.UNSUPPORTED_API_ENDPOINT for v in res.hard_violations)
        assert any("POST /api/auth/signin" in fb for fb in res.repair_feedback)
        assert res.grounding_score < 1.0

    async def test_gate_rejects_hallucinated_symbol(self):
        catalog = EvidenceCatalog(
            [
                EvidenceItem(
                    evidence_id="E-SYM-1",
                    kind="target_symbol",
                    value="cachetools.LRUCache",
                    source="cachetools",
                ),
            ]
        )

        test_code = """
from cachetools import NonExistentMagicCache

def test_magic():
    c = NonExistentMagicCache()
    assert c is not None
"""
        gate = AutomationCodeQualityGate()
        res = await gate.evaluate(
            generated_files={"tests/test_cache.py": test_code},
            target_entrypoint="cachetools.LRUCache",
            evidence_catalog=catalog,
        )

        assert res.status == "REJECTED"
        assert any(v.code == CodeViolationCode.HALLUCINATED_SYMBOL for v in res.hard_violations)

    async def test_gate_passes_when_claims_supported(self):
        catalog = EvidenceCatalog(
            [
                EvidenceItem(
                    evidence_id="E-API-1",
                    kind="api_endpoint",
                    value="POST /api/auth/login",
                    source="src/auth.py",
                ),
                EvidenceItem(
                    evidence_id="E-FLD-1",
                    kind="model_field",
                    value="email",
                    source="src/auth.py",
                ),
            ]
        )

        test_code = """
import requests

def test_valid_login():
    resp = requests.post("/api/auth/login", json={"email": "a@b.com"})
    assert resp.status_code == 200
"""
        gate = AutomationCodeQualityGate()
        res = await gate.evaluate(
            generated_files={"tests/test_auth.py": test_code},
            target_entrypoint="auth_api",
            evidence_catalog=catalog,
        )

        assert res.status == "PASS"
        assert res.allow_final_pass is True
        assert res.grounding_score == 1.0
        assert len(res.hard_violations) == 0

    async def test_gate_needs_review_when_model_field_is_unknown(self):
        catalog = EvidenceCatalog(
            [
                EvidenceItem(
                    evidence_id="E-API-1",
                    kind="api_endpoint",
                    value="POST /api/auth/login",
                    source="src/auth.py",
                ),
            ]
        )

        # "email" is not in catalog -> UNKNOWN model_field
        test_code = """
import requests

def test_valid_login():
    resp = requests.post("/api/auth/login", json={"email": "a@b.com"})
    assert resp.status_code == 200
"""
        gate = AutomationCodeQualityGate()
        res = await gate.evaluate(
            generated_files={"tests/test_auth.py": test_code},
            target_entrypoint="auth_api",
            evidence_catalog=catalog,
        )

        assert res.status == "NEEDS_REVIEW"
        assert res.allow_final_pass is False
        assert any(f.status == "UNKNOWN" and f.claim_type == "model_field" for f in res.grounding_findings)
