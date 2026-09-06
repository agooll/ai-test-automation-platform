"""Tests for AutomationCodeQualityGate orchestrator."""

import pytest
from testteller.quality_gate.code_gate import AutomationCodeQualityGate
from testteller.quality_gate.code_models import CodeViolationCode

pytestmark = [pytest.mark.unit]


@pytest.mark.asyncio
async def test_code_gate_rejects_empty_files():
    gate = AutomationCodeQualityGate()
    res = await gate.evaluate({})
    assert res.status == "REJECTED"
    assert res.allow_execution is False
    assert res.allow_final_pass is False


@pytest.mark.asyncio
async def test_code_gate_rejects_assert_true():
    gate = AutomationCodeQualityGate()
    files = {
        "tests/test_fake.py": """
def test_fake_pass():
    assert True
"""
    }
    res = await gate.evaluate(files)
    assert res.status == "REJECTED"
    assert res.allow_final_pass is False
    codes = [v.code for v in res.hard_violations]
    assert CodeViolationCode.ASSERT_ALWAYS_TRUE in codes
    assert len(res.repair_feedback) > 0


@pytest.mark.asyncio
async def test_code_gate_rejects_swallowed_exception():
    gate = AutomationCodeQualityGate()
    files = {
        "tests/test_swallow.py": """
def test_hidden_failure():
    try:
        raise ValueError("error")
    except:
        pass
"""
    }
    res = await gate.evaluate(files)
    assert res.status == "REJECTED"
    codes = [v.code for v in res.hard_violations]
    assert CodeViolationCode.SWALLOWED_EXCEPTION in codes


@pytest.mark.asyncio
async def test_code_gate_accepts_valid_test():
    gate = AutomationCodeQualityGate()
    files = {
        "tests/test_lru.py": """
from cachetools import LRUCache

def test_lru_behavior():
    cache = LRUCache(maxsize=2)
    cache['a'] = 1
    assert cache['a'] == 1
    assert cache.currsize == 1
"""
    }
    res = await gate.evaluate(files, target_entrypoint="cachetools.LRUCache")
    assert res.status == "PASS"
    assert res.allow_execution is True
    assert res.allow_final_pass is True
    assert res.vacuity_score == 1.0
    assert len(res.hard_violations) == 0


@pytest.mark.asyncio
async def test_code_gate_vacuity_score_calculation():
    gate = AutomationCodeQualityGate()
    files = {
        "tests/test_mixed.py": """
def test_bad():
    assert True
"""
    }
    res = await gate.evaluate(files)
    assert res.vacuity_score < 1.0


@pytest.mark.asyncio
async def test_code_gate_unknown_claim_yields_needs_review_and_no_final_pass():
    gate = AutomationCodeQualityGate()
    files = {
        "tests/test_api.py": """
import requests

def test_call():
    r = requests.get("https://api.example.com/api/v1/unknown_action")
    assert r.status_code == 200
"""
    }
    res = await gate.evaluate(files)
    assert res.status == "NEEDS_REVIEW"
    assert res.allow_final_pass is False
    assert res.allow_execution is True
    assert any(f.status == "UNKNOWN" for f in res.grounding_findings)


@pytest.mark.asyncio
async def test_code_gate_rejects_fake_pytest_raises_and_time_bypass():
    gate = AutomationCodeQualityGate()
    files = {
        "tests/test_bypass.py": """
import pytest
import time

def test_time_and_raises_bypass():
    t = time.time()
    with pytest.raises(ValueError):
        raise ValueError("fake")
"""
    }
    res = await gate.evaluate(files, target_entrypoint="cachetools.LRUCache")
    assert res.status == "REJECTED"
    assert res.allow_final_pass is False
    assert res.allow_execution is False
    codes = [v.code for v in res.hard_violations]
    assert CodeViolationCode.NO_SUT_INTERACTION in codes

