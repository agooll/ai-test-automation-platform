"""Unit tests for Stage 4 Anti-Fake Evaluation metrics and suites."""

from pathlib import Path
import pytest

pytestmark = [pytest.mark.unit]

from testteller.quality_gate.anti_fake_metrics import (
    build_standard_evidence_catalog,
    evaluate_hallucination_suite,
    evaluate_legitimate_suite,
    evaluate_repair_weakening_suite,
    evaluate_vacuous_suite,
    run_full_anti_fake_evaluation,
)
from testteller.quality_gate.code_gate import AutomationCodeQualityGate

QUALITY_EVAL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "evals" / "quality"


@pytest.mark.asyncio
async def test_vacuous_suite_100_percent_detection():
    gate = AutomationCodeQualityGate()
    vac_dir = QUALITY_EVAL_DIR / "vacuous"
    total, detected, records = await evaluate_vacuous_suite(vac_dir, gate)
    assert total >= 5
    assert detected == total, f"Vacuous tests missed: {[r for r in records if not r['detected']]}"


@pytest.mark.asyncio
async def test_hallucination_suite_100_percent_detection():
    gate = AutomationCodeQualityGate()
    catalog = build_standard_evidence_catalog()
    hal_dir = QUALITY_EVAL_DIR / "hallucination"
    total, detected, records = await evaluate_hallucination_suite(hal_dir, gate, catalog)
    assert total >= 4
    assert detected == total, f"Hallucination tests missed: {[r for r in records if not r['detected']]}"


def test_repair_weakening_suite_100_percent_detection():
    cases_json = QUALITY_EVAL_DIR / "repair_weakening" / "cases.json"
    total, detected, records = evaluate_repair_weakening_suite(cases_json)
    assert total >= 8
    assert detected == total, f"Weakening patterns missed: {[r for r in records if not r['correct']]}"


@pytest.mark.asyncio
async def test_legitimate_suite_zero_false_rejections():
    gate = AutomationCodeQualityGate()
    catalog = build_standard_evidence_catalog()
    legit_dir = QUALITY_EVAL_DIR / "legitimate"
    total, passed, records = await evaluate_legitimate_suite(legit_dir, gate, catalog)
    assert total >= 3
    assert passed == total, f"Legitimate tests falsely rejected: {[r for r in records if not r['allow_final_pass']]}"


@pytest.mark.asyncio
async def test_run_full_anti_fake_evaluation():
    summary = await run_full_anti_fake_evaluation(QUALITY_EVAL_DIR)
    assert summary.vacuous_test_detection_rate >= 0.95
    assert summary.hallucination_detection_rate >= 0.95
    assert summary.repair_weakening_rate >= 0.95
    assert summary.false_rejection_rate <= 0.05
    assert summary.grounded_claim_rate >= 0.95
    assert summary.quality_adjusted_pass_rate >= 0.95
