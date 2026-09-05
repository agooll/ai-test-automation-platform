"""Canonical data contracts for test-case quality evaluation."""

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ScenarioType(str, Enum):
    NORMAL = "normal"
    ABNORMAL = "abnormal"
    BOUNDARY = "boundary"


class TestStepContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    action: str = Field(min_length=1)
    target: str = Field(min_length=1)
    input_data: str = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    assertions: List[str] = Field(min_length=1)

    @field_validator("action", "target", "input_data", "expected_result", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("must be a string")
        return value.strip()

    @field_validator("assertions")
    @classmethod
    def validate_assertions(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("at least one concrete assertion is required")
        return cleaned


class NormalizedTestCase(BaseModel):
    """Stable internal representation used by every quality-gate stage."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    requirement_ids: List[str] = Field(min_length=1)
    preconditions: List[str] = Field(min_length=1)
    scenario_type: ScenarioType
    priority: Priority
    steps: List[TestStepContract] = Field(min_length=1)
    assertions: List[str] = Field(min_length=1)
    source_refs: List[str] = Field(default_factory=list)
    test_type: Optional[str] = None
    feature: Optional[str] = None
    expected_final_state: Optional[str] = None
    coverage_exemption_reason: Optional[str] = None

    @field_validator("id", "title")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("requirement_ids", "preconditions", "assertions", "source_refs")
    @classmethod
    def clean_list(cls, value: List[str]) -> List[str]:
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class TestCaseCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: List[NormalizedTestCase] = Field(min_length=1)


class SemanticIssue(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    field: Optional[str] = None


class SemanticReviewResult(BaseModel):
    """Validated output contract for the optional AI reviewer."""

    status: Literal["pass", "fail", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0)
    issues: List[SemanticIssue] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)


class RuleViolation(BaseModel):
    code: str
    field: str
    message: str
    severity: str = "error"


class CoverageFinding(BaseModel):
    requirement_id: str
    missing_scenarios: List[ScenarioType] = Field(default_factory=list)
    duplicate_case_ids: List[str] = Field(default_factory=list)
    message: str
    severity: str = "error"
