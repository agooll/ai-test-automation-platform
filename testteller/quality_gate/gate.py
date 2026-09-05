"""Quality gate orchestration and final decision policy."""

from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field

from testteller.automator_agent.parser.markdown_parser import MarkdownTestCaseParser, TestCase

from .models import CoverageFinding, NormalizedTestCase, RuleViolation, SemanticReviewResult, TestCaseCollection
from .normalizer import normalize_cases
from .reviewer import AIReviewSkill
from .rules import validate_case, validate_case_ids, validate_collection


class QualityGateResult(BaseModel):
    status: str
    hard_rule_errors: list[RuleViolation] = Field(default_factory=list)
    coverage_findings: list[CoverageFinding] = Field(default_factory=list)
    semantic_review: Optional[SemanticReviewResult] = None
    recommendation: str
    allow_storage: bool = False
    allow_automation: bool = False
    normalized_cases: Optional[TestCaseCollection] = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"normalized_cases"})


class QualityGate:
    def __init__(self, ai_reviewer: Optional[AIReviewSkill] = None):
        self.ai_reviewer = ai_reviewer

    async def evaluate_cases(self, cases: Iterable[TestCase], use_ai: bool = True) -> QualityGateResult:
        cases = list(cases)
        try:
            if all(isinstance(case, NormalizedTestCase) for case in cases):
                collection = TestCaseCollection(cases=cases)
            else:
                collection = normalize_cases(cases)
        except Exception as error:
            return QualityGateResult(status="REJECTED", recommendation=f"normalization failed: {error}")

        hard_errors = validate_case_ids(collection)
        for case in collection.cases:
            hard_errors.extend(validate_case(case))
        coverage = validate_collection(collection)
        if hard_errors or coverage:
            return QualityGateResult(
                status="REJECTED",
                hard_rule_errors=hard_errors,
                coverage_findings=coverage,
                recommendation="Fix deterministic schema and coverage violations before semantic review.",
                normalized_cases=collection,
            )

        semantic: Optional[SemanticReviewResult] = None
        if use_ai and self.ai_reviewer:
            semantic = await self.ai_reviewer.review(collection)
            if semantic.status == "fail":
                return QualityGateResult(status="REJECTED", semantic_review=semantic, recommendation="AI semantic review found blocking issues.", normalized_cases=collection)
            if semantic.status != "pass":
                return QualityGateResult(status="NEEDS_REVIEW", semantic_review=semantic, recommendation="Manual review is required because semantic review is uncertain or unavailable.", normalized_cases=collection)
        elif use_ai:
            return QualityGateResult(status="NEEDS_REVIEW", recommendation="AI semantic reviewer is not configured.", normalized_cases=collection)

        return QualityGateResult(status="PASS", semantic_review=semantic, recommendation="All deterministic and semantic quality gates passed.", allow_storage=True, allow_automation=True, normalized_cases=collection)

    async def evaluate_markdown(self, content: str, use_ai: bool = True) -> QualityGateResult:
        parser = MarkdownTestCaseParser()
        cases = parser.parse_content(content)
        if not cases:
            return QualityGateResult(status="REJECTED", recommendation="No structured test cases were found.")
        return await self.evaluate_cases(cases, use_ai=use_ai)
