"""Deterministic quality rules. No LLM calls are made in this module."""

import re
from collections import defaultdict
from typing import Iterable, List

from .models import CoverageFinding, NormalizedTestCase, RuleViolation, ScenarioType, TestCaseCollection

VAGUE_WORDS = {"正常", "成功即可", "功能正常", "符合预期", "没有问题", "as expected", "works fine"}
PLACEHOLDERS = {"todo", "fixme", "tbd", "待补充", "待确认", "待完善", "n/a"}


def _text_contains(text: str, words: set[str]) -> str | None:
    lowered = text.lower()
    return next((word for word in words if word.lower() in lowered), None)


def validate_case(case: NormalizedTestCase) -> List[RuleViolation]:
    violations: List[RuleViolation] = []
    all_text = [case.id, case.title, *case.requirement_ids, *case.preconditions, *case.assertions]
    all_text.extend(
        value
        for step in case.steps
        for value in (step.action, step.target, step.input_data, step.expected_result, *step.assertions)
    )
    for value in all_text:
        placeholder = _text_contains(value, PLACEHOLDERS)
        if placeholder:
            violations.append(RuleViolation(code="PLACEHOLDER_TEXT", field="case", message=f"placeholder text is not allowed: {placeholder}"))
        vague = _text_contains(value, VAGUE_WORDS)
        if vague:
            violations.append(RuleViolation(code="VAGUE_TEXT", field="case", message=f"vague text is not allowed: {vague}"))

    if len({item.lower() for item in case.requirement_ids}) != len(case.requirement_ids):
        violations.append(RuleViolation(code="DUPLICATE_REQUIREMENT", field="requirement_ids", message="requirement IDs must be unique"))
    if not case.source_refs:
        violations.append(RuleViolation(code="MISSING_TRACE", field="source_refs", message="at least one source reference is required"))
    if [step.index for step in case.steps] != list(range(1, len(case.steps) + 1)):
        violations.append(RuleViolation(code="STEP_SEQUENCE", field="steps", message="step indexes must be continuous"))
    for step in case.steps:
        if not step.action.strip():
            violations.append(RuleViolation(code="MISSING_ACTION", field=f"steps[{step.index}].action", message="action is required"))
        if not step.target.strip():
            violations.append(RuleViolation(code="MISSING_TARGET", field=f"steps[{step.index}].target", message="operation target is required"))
        if not step.input_data.strip():
            violations.append(RuleViolation(code="MISSING_INPUT", field=f"steps[{step.index}].input_data", message="input data is required; use an explicit no-input explanation when applicable"))
        if not step.expected_result.strip():
            violations.append(RuleViolation(code="MISSING_EXPECTED_RESULT", field=f"steps[{step.index}].expected_result", message="expected result is required"))
        if not step.assertions:
            violations.append(RuleViolation(code="MISSING_STEP_ASSERTION", field=f"steps[{step.index}].assertions", message="at least one step assertion is required"))
    if not case.assertions:
        violations.append(RuleViolation(code="MISSING_ASSERTION", field="assertions", message="at least one concrete assertion is required"))
    return violations


def validate_collection(collection: TestCaseCollection) -> List[CoverageFinding]:
    findings: List[CoverageFinding] = []
    by_requirement: dict[str, list[NormalizedTestCase]] = defaultdict(list)
    for case in collection.cases:
        for requirement_id in case.requirement_ids:
            by_requirement[requirement_id].append(case)
    for requirement_id, cases in by_requirement.items():
        present = {case.scenario_type for case in cases}
        missing = [scenario for scenario in ScenarioType if scenario not in present]
        if missing and not all(case.coverage_exemption_reason for case in cases):
            findings.append(CoverageFinding(requirement_id=requirement_id, missing_scenarios=missing, message="requirement is missing normal, abnormal, or boundary coverage"))
        ids = [case.id for case in cases]
        duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicates:
            findings.append(CoverageFinding(requirement_id=requirement_id, duplicate_case_ids=duplicates, message="duplicate test case IDs found"))
        signatures: dict[str, list[str]] = defaultdict(list)
        for case in cases:
            signature = "|".join(
                [case.scenario_type.value, case.title.strip().lower()]
                + [step.action.strip().lower() for step in case.steps]
            )
            signatures[signature].append(case.id)
        for duplicate_ids in signatures.values():
            if len(duplicate_ids) > 1:
                findings.append(CoverageFinding(requirement_id=requirement_id, duplicate_case_ids=duplicate_ids, message="duplicate scenario content found"))
    return findings


def validate_case_ids(collection: TestCaseCollection) -> List[RuleViolation]:
    seen: set[str] = set()
    violations: List[RuleViolation] = []
    for index, case in enumerate(collection.cases):
        key = case.id.lower()
        if key in seen:
            violations.append(RuleViolation(code="DUPLICATE_CASE_ID", field=f"cases[{index}].id", message=f"duplicate test case ID: {case.id}"))
        seen.add(key)
    return violations
