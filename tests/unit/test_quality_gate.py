"""Tests for deterministic and semantic test-case quality gates."""

import pytest

from testteller.quality_gate.gate import QualityGate
from testteller.quality_gate.models import (
    NormalizedTestCase,
    Priority,
    ScenarioType,
    TestCaseCollection,
    TestStepContract,
    SemanticReviewResult,
)
from testteller.quality_gate.reviewer import AIReviewSkill
from testteller.quality_gate.rules import validate_case


def make_case(scenario: ScenarioType, case_id: str = "TC-1") -> NormalizedTestCase:
    return NormalizedTestCase(
        id=case_id,
        title=f"登录-{scenario.value}",
        requirement_ids=["REQ-LOGIN"],
        preconditions=["测试用户已注册，登录页面已打开"],
        scenario_type=scenario,
        priority=Priority.P1,
        steps=[
            TestStepContract(
                index=1,
                action="在用户名输入框输入 test01 并点击登录按钮",
                target="登录表单",
                input_data="用户名=test01，密码=123456",
                expected_result="页面跳转到 /home，响应状态码为 200",
                assertions=["响应状态码等于 200", "当前路径等于 /home"],
            )
        ],
        assertions=["响应状态码等于 200", "页面显示 test01"],
        source_refs=["requirements.md#REQ-LOGIN"],
    )


class StubGenerator:
    def __init__(self, response: str = "{}", error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls = 0

    async def generate_text_async(self, prompt: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


def test_schema_rejects_invalid_priority():
    with pytest.raises(ValueError):
        NormalizedTestCase.model_validate(
            {**make_case(ScenarioType.NORMAL).model_dump(), "priority": "P4"}
        )


def test_hard_rules_reject_missing_step_target():
    case = make_case(ScenarioType.NORMAL).model_copy(
        update={"steps": [make_case(ScenarioType.NORMAL).steps[0].model_copy(update={"target": ""})]}
    )
    violations = validate_case(case)
    assert any(item.code == "MISSING_TARGET" for item in violations)


@pytest.mark.asyncio
async def test_collection_requires_normal_abnormal_and_boundary():
    result = await QualityGate().evaluate_cases([make_case(ScenarioType.NORMAL)], use_ai=False)
    assert result.status == "REJECTED"
    assert {item.value for item in result.coverage_findings[0].missing_scenarios} == {"abnormal", "boundary"}


@pytest.mark.asyncio
async def test_hard_rule_failure_does_not_call_ai():
    generator = StubGenerator(
        '{"status":"pass","confidence":1,"issues":[],"suggestions":[],"evidence":[]}'
    )
    gate = QualityGate(AIReviewSkill(generator))
    invalid = make_case(ScenarioType.NORMAL).model_copy(
        update={"steps": [make_case(ScenarioType.NORMAL).steps[0].model_copy(update={"target": ""})]}
    )
    result = await gate.evaluate_cases([invalid], use_ai=True)
    assert result.status == "REJECTED"
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_ai_failure_requires_manual_review():
    generator = StubGenerator(error=RuntimeError("provider unavailable"))
    gate = QualityGate(AIReviewSkill(generator))
    cases = [make_case(ScenarioType.NORMAL, "TC-1"), make_case(ScenarioType.ABNORMAL, "TC-2"), make_case(ScenarioType.BOUNDARY, "TC-3")]
    result = await gate.evaluate_cases(cases, use_ai=True)
    assert result.status == "NEEDS_REVIEW"
    assert result.allow_storage is False
    assert result.allow_automation is False


@pytest.mark.asyncio
async def test_ai_pass_allows_storage_and_automation():
    generator = StubGenerator(
        '{"status":"pass","confidence":0.95,"issues":[],"suggestions":[],"evidence":["REQ-LOGIN"]}'
    )
    gate = QualityGate(AIReviewSkill(generator))
    cases = [make_case(ScenarioType.NORMAL, "TC-1"), make_case(ScenarioType.ABNORMAL, "TC-2"), make_case(ScenarioType.BOUNDARY, "TC-3")]
    result = await gate.evaluate_cases(cases, use_ai=True)
    assert result.status == "PASS"
    assert result.allow_storage is True
    assert result.allow_automation is True
    assert generator.calls == 1
