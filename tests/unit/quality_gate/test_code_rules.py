"""Tests for deterministic code rules."""

import pytest
from testteller.quality_gate.code_models import CodeViolationCode
from testteller.quality_gate.code_rules import (
    check_placeholders,
    check_syntax_and_parse,
    validate_test_functions,
)
from testteller.quality_gate.python_analyzer import analyze_test_module

pytestmark = [pytest.mark.unit]


def test_check_syntax_and_parse_valid():
    code = "def test_hello(): assert 1 + 1 == 2"
    tree, err = check_syntax_and_parse(code, "test_sample.py")
    assert tree is not None
    assert err is None


def test_check_syntax_and_parse_invalid():
    code = "def test_broken( assert 1"
    tree, err = check_syntax_and_parse(code, "test_broken.py")
    assert tree is None
    assert err is not None
    assert err.code == CodeViolationCode.CODE_PARSE_ERROR


def test_check_placeholders():
    code = """
# TODO: Implement this test
def test_something():
    assert True # FIXME
"""
    violations = check_placeholders(code, "test_placeholder.py")
    assert len(violations) >= 2
    assert all(v.code == CodeViolationCode.PLACEHOLDER_CODE for v in violations)


def test_validate_test_functions_tautology():
    code = """
def test_tautology():
    assert True
"""
    analyses = analyze_test_module(code)
    violations = validate_test_functions(analyses, "test_tautology.py")
    codes = [v.code for v in violations]
    assert CodeViolationCode.ASSERT_ALWAYS_TRUE in codes


def test_validate_test_functions_swallowed():
    code = """
def test_swallow():
    try:
        x = 1 / 0
    except Exception:
        pass
"""
    analyses = analyze_test_module(code)
    violations = validate_test_functions(analyses, "test_swallow.py")
    codes = [v.code for v in violations]
    assert CodeViolationCode.SWALLOWED_EXCEPTION in codes


def test_validate_test_functions_no_sut():
    code = """
def test_no_sut():
    x = 10
    assert x == 10
"""
    analyses = analyze_test_module(code)
    violations = validate_test_functions(analyses, "test_no_sut.py")
    codes = [v.code for v in violations]
    assert CodeViolationCode.NO_SUT_INTERACTION in codes


def test_validate_test_functions_skip():
    code = """
import pytest

@pytest.mark.skip(reason="unconditional skip")
def test_skipped():
    assert True
"""
    analyses = analyze_test_module(code)
    violations = validate_test_functions(analyses, "test_skipped.py")
    codes = [v.code for v in violations]
    assert CodeViolationCode.UNCONDITIONAL_SKIP in codes


def test_pytest_raises_without_sut_fails_rules():
    code = """
import pytest

def test_manufactured():
    with pytest.raises(ValueError):
        raise ValueError("fake")
"""
    analyses = analyze_test_module(code, target_entrypoint="cachetools.LRUCache")
    violations = validate_test_functions(analyses, "test_raises.py")
    codes = [v.code for v in violations]
    assert CodeViolationCode.NO_SUT_INTERACTION in codes
    assert CodeViolationCode.NO_SUT_DEPENDENT_ASSERTION in codes


def test_pytest_raises_with_sut_passes_rules():
    code = """
import pytest
from cachetools import LRUCache

def test_genuine():
    c = LRUCache(maxsize=1)
    with pytest.raises(KeyError):
        _ = c['missing']
"""
    analyses = analyze_test_module(code, target_entrypoint="cachetools.LRUCache")
    violations = validate_test_functions(analyses, "test_raises.py")
    assert len(violations) == 0


def test_stdlib_time_bypass_fails_rules():
    code = """
import time

def test_time_only():
    t = time.time()
    assert t > 0
"""
    analyses = analyze_test_module(code, target_entrypoint="cachetools.LRUCache")
    violations = validate_test_functions(analyses, "test_time.py")
    codes = [v.code for v in violations]
    assert CodeViolationCode.NO_SUT_INTERACTION in codes

