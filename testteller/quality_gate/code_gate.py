"""Main Automation Code Quality Gate coordinating deterministic AST rules and anti-counterfeit analysis."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .code_models import (
    ClaimItem,
    CodeQualityGateResult,
    CodeViolation,
    CodeViolationCode,
    EvidenceItem,
    GroundingFinding,
)
from .code_rules import (
    check_placeholders,
    check_syntax_and_parse,
    validate_test_functions,
)
from .grounding import (
    CodeClaimExtractor,
    EvidenceCatalog,
    GroundingValidator,
    RepoSymbolExtractor,
)
from .python_analyzer import analyze_test_module

logger = logging.getLogger(__name__)


class AutomationCodeQualityGate:
    """Evaluates generated test code against AST anti-counterfeit rules and assertion dependencies."""

    def __init__(self, reviewer: Optional[Any] = None):
        self.reviewer = reviewer

    async def evaluate(
        self,
        generated_files: Dict[str, str],
        requirement: str = "",
        target_entrypoint: Optional[str] = None,
        retrieved_context: Optional[List[Any]] = None,
        use_ai: bool = False,
        evidence_catalog: Optional[EvidenceCatalog] = None,
        repo_path: Optional[str] = None,
    ) -> CodeQualityGateResult:
        """Run deterministic AST rules and grounding validation on generated test files."""
        hard_violations: List[CodeViolation] = []
        grounding_findings: List[GroundingFinding] = []
        total_tests = 0
        repair_feedback: List[str] = []
        all_claims: List[ClaimItem] = []

        if not generated_files:
            hard_violations.append(
                CodeViolation(
                    code=CodeViolationCode.NO_TEST_DISCOVERED,
                    file_path="workspace",
                    message="No test files were generated.",
                    severity="error",
                    suggestion="Generate executable test files containing test functions.",
                )
            )
            return CodeQualityGateResult(
                status="REJECTED",
                hard_violations=hard_violations,
                grounding_findings=[],
                vacuity_score=0.0,
                grounding_score=1.0,
                total_tests_scanned=0,
                allow_execution=False,
                allow_final_pass=False,
                repair_feedback=["No test files were generated."],
            )

        # 0. Build or enrich EvidenceCatalog
        if isinstance(evidence_catalog, EvidenceCatalog):
            catalog = evidence_catalog
        else:
            catalog = EvidenceCatalog()
            if isinstance(evidence_catalog, (list, tuple)):
                for it in evidence_catalog:
                    if isinstance(it, EvidenceItem):
                        catalog.add_item(it)
                    elif isinstance(it, dict) and "evidence_id" in it and "kind" in it and "value" in it:
                        try:
                            catalog.add_item(
                                EvidenceItem(
                                    evidence_id=str(it["evidence_id"]),
                                    kind=it["kind"],
                                    value=str(it["value"]),
                                    source=str(it.get("source", "catalog")),
                                    source_chunk_id=it.get("source_chunk_id"),
                                    confidence=float(it.get("confidence", 1.0)),
                                )
                            )
                        except Exception:
                            pass

        if target_entrypoint:
            entrypoint_symbols = RepoSymbolExtractor.extract_from_entrypoint(
                target_entrypoint, repo_root=repo_path
            )
            catalog.add_items(entrypoint_symbols)

        if retrieved_context:
            for ctx_item in retrieved_context:
                if isinstance(ctx_item, EvidenceItem):
                    catalog.add_item(ctx_item)
                elif isinstance(ctx_item, dict):
                    if "evidence_id" in ctx_item and "kind" in ctx_item and "value" in ctx_item:
                        try:
                            catalog.add_item(
                                EvidenceItem(
                                    evidence_id=str(ctx_item["evidence_id"]),
                                    kind=ctx_item["kind"],
                                    value=str(ctx_item["value"]),
                                    source=str(ctx_item.get("source", "catalog")),
                                    source_chunk_id=ctx_item.get("source_chunk_id"),
                                    confidence=float(ctx_item.get("confidence", 1.0)),
                                )
                            )
                        except Exception:
                            pass

        test_files_found = 0

        for file_path, code in generated_files.items():
            if not file_path.endswith(".py"):
                continue

            test_files_found += 1

            # 1. Syntax check
            tree, syntax_err = check_syntax_and_parse(code, file_path)
            if syntax_err:
                hard_violations.append(syntax_err)
                continue

            # 2. Placeholders check
            placeholders = check_placeholders(code, file_path)
            hard_violations.extend(placeholders)

            # 3. Test functions & dependency analysis
            analyses = analyze_test_module(code, target_entrypoint=target_entrypoint)
            total_tests += len(analyses)

            # 4. Anti-counterfeit rule validation
            rule_violations = validate_test_functions(
                analyses=analyses,
                file_path=file_path,
                target_entrypoint=target_entrypoint,
            )
            hard_violations.extend(rule_violations)

            # 5. Extract claims for grounding analysis
            claim_extractor = CodeClaimExtractor(
                file_path=file_path,
                target_entrypoint=target_entrypoint,
            )
            claim_extractor.visit(tree)
            all_claims.extend(claim_extractor.claims)

        if test_files_found == 0:
            hard_violations.append(
                CodeViolation(
                    code=CodeViolationCode.NO_TEST_DISCOVERED,
                    file_path="workspace",
                    message="No Python (.py) test files found among generated files.",
                    severity="error",
                    suggestion="Generate at least one Python test file.",
                )
            )

        # 6. Validate claims against EvidenceCatalog
        if all_claims:
            g_violations, g_findings, g_score = GroundingValidator.validate(
                claims=all_claims,
                catalog=catalog,
            )
            hard_violations.extend(g_violations)
            grounding_findings.extend(g_findings)
            grounding_score = g_score
        else:
            grounding_score = 1.0

        # Calculate vacuity score: 1.0 if clean, 0.0 if saturated with AST violations
        ast_error_count = sum(
            1
            for v in hard_violations
            if v.severity == "error"
            and v.code
            not in (
                CodeViolationCode.UNSUPPORTED_API_ENDPOINT,
                CodeViolationCode.UNSUPPORTED_UI_SELECTOR,
                CodeViolationCode.HALLUCINATED_SYMBOL,
            )
        )
        if total_tests == 0 and ast_error_count > 0:
            vacuity_score = 0.0
        elif ast_error_count > 0:
            vacuity_score = max(0.0, 1.0 - (ast_error_count / max(total_tests, 1)))
        else:
            vacuity_score = 1.0

        # Construct actionable repair feedback
        for v in hard_violations:
            loc = f"{v.file_path}"
            if v.line_number:
                loc += f":{v.line_number}"
            if v.function_name:
                loc += f" in '{v.function_name}'"
            item_msg = f"- [{v.code.value}] {loc}: {v.message}"
            if v.suggestion:
                item_msg += f" -> Suggestion: {v.suggestion}"
            repair_feedback.append(item_msg)

        has_errors = any(v.severity == "error" for v in hard_violations)
        has_unknown_business_claims = any(
            f.status == "UNKNOWN" and f.claim_type in ("api_endpoint", "target_symbol", "ui_selector")
            for f in grounding_findings
        )

        if has_errors:
            status = "REJECTED"
            allow_execution = False
            allow_final_pass = False
        elif has_unknown_business_claims:
            status = "NEEDS_REVIEW"
            allow_execution = True
            allow_final_pass = False
            repair_feedback.append(
                "- [NEEDS_REVIEW] Test code contains unverified business claims (API/UI/symbols) that lack authoritative project evidence."
            )
        else:
            status = "PASS"
            allow_execution = True
            allow_final_pass = True

        logger.info(
            "AutomationCodeQualityGate verdict: status=%s, violations=%d, total_tests=%d, vacuity_score=%.2f, grounding_score=%.2f",
            status,
            len(hard_violations),
            total_tests,
            vacuity_score,
            grounding_score,
        )

        return CodeQualityGateResult(
            status=status,
            hard_violations=hard_violations,
            grounding_findings=grounding_findings,
            vacuity_score=round(vacuity_score, 4),
            grounding_score=round(grounding_score, 4),
            total_tests_scanned=total_tests,
            allow_execution=allow_execution,
            allow_final_pass=allow_final_pass,
            repair_feedback=repair_feedback,
        )
