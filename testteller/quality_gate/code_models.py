"""Canonical data contracts for automation code quality, anti-counterfeiting, and grounding."""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class CodeViolationCode(str, Enum):
    CODE_PARSE_ERROR = "CODE_PARSE_ERROR"
    NO_TEST_DISCOVERED = "NO_TEST_DISCOVERED"
    EMPTY_TEST_BODY = "EMPTY_TEST_BODY"
    PLACEHOLDER_CODE = "PLACEHOLDER_CODE"
    ASSERT_ALWAYS_TRUE = "ASSERT_ALWAYS_TRUE"
    CONSTANT_ASSERTION = "CONSTANT_ASSERTION"
    TRIVIAL_NOT_NONE_ASSERTION = "TRIVIAL_NOT_NONE_ASSERTION"
    NO_SUT_INTERACTION = "NO_SUT_INTERACTION"
    NO_SUT_DEPENDENT_ASSERTION = "NO_SUT_DEPENDENT_ASSERTION"
    TARGET_FULLY_MOCKED = "TARGET_FULLY_MOCKED"
    SWALLOWED_EXCEPTION = "SWALLOWED_EXCEPTION"
    UNCONDITIONAL_SKIP = "UNCONDITIONAL_SKIP"
    UNSUPPORTED_XFAIL = "UNSUPPORTED_XFAIL"
    UNREACHABLE_ASSERTION = "UNREACHABLE_ASSERTION"
    HALLUCINATED_SYMBOL = "HALLUCINATED_SYMBOL"
    UNSUPPORTED_API_ENDPOINT = "UNSUPPORTED_API_ENDPOINT"
    UNSUPPORTED_UI_SELECTOR = "UNSUPPORTED_UI_SELECTOR"


class CodeViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: CodeViolationCode
    file_path: str
    function_name: Optional[str] = None
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    message: str
    severity: Literal["error", "warning"] = "error"
    suggestion: Optional[str] = None


class EvidenceItem(BaseModel):
    """A machine-verifiable factual evidence item discovered from codebase or docs."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    kind: Literal[
        "api_endpoint",
        "ui_selector",
        "model_field",
        "target_symbol",
        "config",
        "auth_pattern",
    ]
    value: str
    source: str
    source_chunk_id: Optional[str] = None
    confidence: float = 1.0


class ClaimItem(BaseModel):
    """An explicit factual claim extracted from generated test code."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    kind: Literal[
        "api_endpoint",
        "ui_selector",
        "model_field",
        "target_symbol",
    ]
    value: str
    file_path: str
    line_number: Optional[int] = None
    matched_evidence_id: Optional[str] = None
    status: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"] = "UNKNOWN"
    reason: Optional[str] = None


class GroundingFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_type: str
    claim_value: str
    status: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    evidence_id: Optional[str] = None
    message: str
    source_file: Optional[str] = None


class CodeSemanticReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pass", "fail", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0)
    issues: List[dict] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class CodeQualityGateResult(BaseModel):
    """Detailed verdict and diagnosis for generated automation code."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["PASS", "REJECTED", "NEEDS_REVIEW"]
    hard_violations: List[CodeViolation] = Field(default_factory=list)
    grounding_findings: List[GroundingFinding] = Field(default_factory=list)
    vacuity_score: float = Field(ge=0.0, le=1.0, default=1.0)
    grounding_score: float = Field(ge=0.0, le=1.0, default=1.0)
    total_tests_scanned: int = 0
    semantic_review: Optional[CodeSemanticReview] = None
    allow_execution: bool = True
    allow_final_pass: bool = False
    repair_feedback: List[str] = Field(default_factory=list)

    def as_dict(self) -> dict:
        return self.model_dump(mode="json")
