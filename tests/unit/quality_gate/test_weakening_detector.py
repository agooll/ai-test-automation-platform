"""Unit tests for AST-based Repair Weakening Detector."""

import pytest

pytestmark = [pytest.mark.unit]

from testteller.quality_gate.code_gate import AutomationCodeQualityGate
from testteller.quality_gate.code_models import CodeViolationCode
from testteller.quality_gate.weakening_detector import RepairWeakeningDetector


def test_detect_deleted_assertion():
    before = """
def test_user_creation():
    user = create_user("alice")
    assert user.name == "alice"
    assert user.is_active is True
    assert user.role == "admin"
"""
    after = """
def test_user_creation():
    user = create_user("alice")
    assert user.name == "alice"
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_WEAKENED_ASSERTION for v in res.violations)
    assert res.before_assertion_count == 3
    assert res.after_assertion_count == 1


def test_detect_deleted_test_function():
    before = """
def test_one():
    assert 1 == 1

def test_two():
    assert 2 == 2
"""
    after = """
def test_one():
    assert 1 == 1
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_WEAKENED_ASSERTION and "test_two" in v.test_name for v in res.violations)


def test_detect_equality_weakened_to_is_not_none():
    before = """
def test_calculate():
    res = calculate_total([10, 20])
    assert res == 30
"""
    after = """
def test_calculate():
    res = calculate_total([10, 20])
    assert res is not None
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_EQUALITY_WEAKENED for v in res.violations)


def test_detect_equality_weakened_to_truthiness():
    before = """
def test_status():
    status = get_service_status()
    assert status == "UP"
"""
    after = """
def test_status():
    status = get_service_status()
    assert status
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_EQUALITY_WEAKENED for v in res.violations)


def test_detect_exception_broadened():
    before = """
def test_missing_key():
    with pytest.raises(KeyError):
        cache["nonexistent"]
"""
    after = """
def test_missing_key():
    with pytest.raises(Exception):
        cache["nonexistent"]
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_EXCEPTION_BROADENED for v in res.violations)


def test_detect_swallowed_exception_in_repair():
    before = """
def test_api_call():
    client = APIClient()
    res = client.fetch()
    assert res.status == 200
"""
    after = """
def test_api_call():
    client = APIClient()
    try:
        res = client.fetch()
        assert res.status == 200
    except Exception:
        pass
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_EXCEPTION_BROADENED for v in res.violations)


def test_detect_target_mocked_in_repair():
    before = """
def test_db_lookup():
    db = RealDatabase()
    res = db.find_user(1)
    assert res.id == 1
"""
    after = """
from unittest.mock import MagicMock

def test_db_lookup():
    db = MagicMock()
    db.find_user.return_value.id = 1
    res = db.find_user(1)
    assert res.id == 1
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_TARGET_MOCKED for v in res.violations)


def test_detect_skip_added_in_repair():
    before = """
def test_flaky_service():
    res = ping()
    assert res == "pong"
"""
    after = """
import pytest

@pytest.mark.skip(reason="fails sometimes")
def test_flaky_service():
    res = ping()
    assert res == "pong"
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_SKIP_OR_XFAIL_ADDED for v in res.violations)


def test_detect_loosened_expected_bound():
    before = """
def test_item_count():
    items = load_items()
    assert len(items) == 5
"""
    after = """
def test_item_count():
    items = load_items()
    assert len(items) >= 0
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is True
    assert any(v.code == CodeViolationCode.REPAIR_EXPECTED_VALUE_LOOSENED for v in res.violations)


def test_legitimate_repair_not_flagged():
    before = """
from my_module import wrong_func

def test_legit():
    res = wrong_func("arg")
    assert res == "success"
"""
    after = """
from my_module import correct_func

def test_legit():
    res = correct_func("arg")
    assert res == "success"
"""
    res = RepairWeakeningDetector.detect(before, after)
    assert res.is_weakened is False
    assert len(res.violations) == 0


@pytest.mark.asyncio
async def test_code_gate_rejects_weakened_repair():
    gate = AutomationCodeQualityGate()
    before_files = {
        "tests/test_demo.py": """
from cachetools import LRUCache

def test_lru():
    cache = LRUCache(maxsize=2)
    cache['a'] = 1
    assert cache['a'] == 1
    assert len(cache) == 1
"""
    }
    weakened_files = {
        "tests/test_demo.py": """
from cachetools import LRUCache

def test_lru():
    cache = LRUCache(maxsize=2)
    cache['a'] = 1
    assert cache['a'] is not None
"""
    }

    result = await gate.evaluate(
        generated_files=weakened_files,
        target_entrypoint="cachetools.LRUCache",
        previous_files=before_files,
    )

    assert result.status == "REJECTED"
    assert result.allow_execution is False
    assert result.allow_final_pass is False
    assert result.weakening_detected is True
    assert any("REPAIR_WEAKENED_ASSERTION" in fb or "REPAIR_EQUALITY_WEAKENED" in fb for fb in result.repair_feedback)
