"""Adapters from the legacy Markdown parser to the canonical contract."""

import re
from typing import Iterable, List

from testteller.automator_agent.parser.markdown_parser import TestCase, TestStep

from .models import NormalizedTestCase, Priority, ScenarioType, TestCaseCollection, TestStepContract


def _first_nonempty(values: Iterable[str]) -> str:
    return next((value.strip() for value in values if isinstance(value, str) and value.strip()), "")


def _scenario(category: str, test_id: str) -> ScenarioType:
    text = f"{category} {test_id}".lower()
    if any(word in text for word in ("boundary", "edge", "边界")):
        return ScenarioType.BOUNDARY
    if any(word in text for word in ("negative", "error", "security", "异常", "失败")):
        return ScenarioType.ABNORMAL
    return ScenarioType.NORMAL


def _priority(value: str | None) -> Priority | None:
    if not value:
        return None
    match = re.search(r"\b(P[0-3])\b", value.upper())
    if match:
        return Priority(match.group(1))
    # Compatibility mapping for older TestTeller outputs.
    legacy = {"HIGH": Priority.P1, "MEDIUM": Priority.P2, "LOW": Priority.P3}
    return legacy.get(value.strip().upper())


def _requirements(case: TestCase) -> List[str]:
    values: List[str] = list(getattr(case, "requirement_ids", []) or [])
    for key, value in case.references.items():
        if not value:
            continue
        for match in re.findall(r"(?:REQ[-_ ]?\w+|需求[-_ ]?\w+)", value, re.I):
            values.append(match)
        if key in {"requirement", "requirements"}:
            values.append(value)
    return list(dict.fromkeys(values))


def _step_contract(step: TestStep, index: int) -> TestStepContract:
    action = step.action or ""
    validation = step.validation or step.validation_details or ""
    target = ""
    input_data = ""
    # Keep the legacy free-text step intact while extracting obvious structure.
    target_match = re.search(r"(?:in|on|at|to|from)\s+([^,.;，。；]+)", action, re.I)
    if target_match:
        target = target_match.group(1).strip()
    if not target and step.technical_details:
        target = step.technical_details.strip()
    input_match = re.search(r"(?:input|enter|with|using|输入|填写)\s+([^,.;，。；]+)", action, re.I)
    if input_match:
        input_data = input_match.group(1).strip()
    return TestStepContract(
        index=index,
        action=action,
        target=target,
        input_data=input_data,
        expected_result=validation,
        assertions=[validation] if validation else [],
    )


def _coalesce_steps(case: TestCase) -> list[TestStep]:
    """Pair legacy Action/Validation rows into executable steps."""
    paired: list[TestStep] = []
    pending: TestStep | None = None
    for step in case.test_steps:
        if step.action:
            if pending is not None:
                paired.append(pending)
            pending = TestStep(
                action=step.action,
                technical_details=step.technical_details,
                validation=step.validation,
                validation_details=step.validation_details,
            )
        elif step.validation and pending is not None:
            pending.validation = step.validation
            pending.validation_details = step.validation_details or pending.validation_details
        elif step.validation:
            paired.append(step)
    if pending is not None:
        paired.append(pending)
    return paired


def _fallback_step(case: TestCase) -> list[TestStep]:
    """Build one structured step for integration/technical legacy cases."""
    action = str(case.prerequisites.get("when", "")).strip()
    target = ""
    if case.technical_contract:
        target = str(case.technical_contract.get("endpoint", "")).strip()
    if not target and case.test_setup:
        target = str(case.test_setup.get("targets", "")).strip()
    target = target or case.feature or case.integration or case.technical_area or "system under test"
    input_data = case.request_payload or (case.prerequisites.get("test_data", "") if case.prerequisites else "")
    input_data = str(input_data).strip() or "No direct input; use the prerequisite system state"
    expected_values = []
    if case.prerequisites.get("then"):
        expected_values.append(str(case.prerequisites["then"]))
    if case.expected_response:
        expected_values.extend(str(value) for value in case.expected_response.values())
    if case.hypothesis:
        expected_values.append(case.hypothesis)
    expected = "; ".join(value for value in expected_values if value.strip()) or case.objective
    return [TestStep(action=action or f"Execute the {case.type or 'test'} scenario", technical_details=target, validation=expected)]


def from_legacy_case(case: TestCase) -> NormalizedTestCase:
    priority = _priority(getattr(case, "priority", None))
    if priority is None:
        raise ValueError(f"{case.id}: missing priority; expected P0/P1/P2/P3")
    legacy_steps = _coalesce_steps(case) or _fallback_step(case)
    steps = [_step_contract(step, index) for index, step in enumerate(legacy_steps, 1)]
    assertions = [step.validation for step in legacy_steps if step.validation]
    if not assertions and case.expected_state:
        assertions = list(case.expected_state.values())
    preconditions = [str(value) for value in case.prerequisites.values() if str(value).strip()]
    return NormalizedTestCase(
        id=case.id,
        title=case.objective or case.feature or case.integration or "",
        requirement_ids=_requirements(case),
        preconditions=preconditions,
        scenario_type=_scenario(case.category, case.id),
        priority=priority,
        steps=steps,
        assertions=assertions,
        source_refs=[value for value in case.references.values() if value],
        test_type=case.type,
        feature=case.feature or case.integration,
        expected_final_state="; ".join(case.expected_state.values()) if case.expected_state else None,
    )


def normalize_cases(cases: Iterable[TestCase]) -> TestCaseCollection:
    return TestCaseCollection(cases=[from_legacy_case(case) for case in cases])
