"""Main Automation Code Quality Gate coordinating deterministic AST rules and anti-counterfeit analysis."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .code_models import (
    CodeQualityGateResult,
    CodeViolation,
    CodeViolationCode,
    GroundingFinding,
)
from .code_rules import (
    check_placeholders,
    check_syntax_and_parse,
    validate_test_functions,
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
        retrieved_context: Optional[List[dict]] = None,
        use_ai: bool = False,
    ) -> CodeQualityGateResult:
        """Run deterministic AST rules on generated test files."""
        hard_violations: List[CodeViolation] = []
        grounding_findings: List[GroundingFinding] = []
        total_tests = 0
        repair_feedback: List[str] = []

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

        # Calculate vacuity score: 1.0 if perfectly clean, 0.0 if saturated with violations
        if total_tests == 0 and hard_violations:
            vacuity_score = 0.0
        elif hard_violations:
            error_count = sum(1 for v in hard_violations if v.severity == "error")
            vacuity_score = max(0.0, 1.0 - (error_count / max(total_tests, 1)))
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
        status = "REJECTED" if has_errors else "PASS"
        allow_execution = not any(
            v.code in (CodeViolationCode.CODE_PARSE_ERROR, CodeViolationCode.NO_TEST_DISCOVERED)
            for v in hard_violations
        )
        allow_final_pass = not has_errors

        logger.info(
            "AutomationCodeQualityGate verdict: status=%s, violations=%d, total_tests=%d, vacuity_score=%.2f",
            status,
            len(hard_violations),
            total_tests,
            vacuity_score,
        )

        return CodeQualityGateResult(
            status=status,
            hard_violations=hard_violations,
            grounding_findings=grounding_findings,
            vacuity_score=round(vacuity_score, 4),
            grounding_score=1.0,
            total_tests_scanned=total_tests,
            allow_execution=allow_execution,
            allow_final_pass=allow_final_pass,
            repair_feedback=repair_feedback,
        )
