"""Tests for Python AST Analyzer and Assertion Dependency Tracking."""

import pytest
from testteller.quality_gate.python_analyzer import analyze_test_module

pytestmark = [pytest.mark.unit]


def test_analyze_tautology_assertions():
    code = """
def test_fake():
    assert True
    assert 1 == 1
    assert "abc" == "abc"
    assert not False
"""
    analyses = analyze_test_module(code)
    assert len(analyses) == 1
    func = analyses[0]
    assert func.name == "test_fake"
    assert len(func.assertions) == 4
    for a in func.assertions:
        assert a.is_tautology is True


def test_analyze_constant_assertions():
    code = """
def test_constants():
    assert 2 > 1
    assert "a" != "b"
"""
    analyses = analyze_test_module(code)
    func = analyses[0]
    for a in func.assertions:
        assert a.is_constant is True


def test_analyze_swallowed_exceptions():
    code = """
def test_swallow_bare():
    try:
        raise ValueError("boom")
    except:
        pass

def test_swallow_broad():
    try:
        raise RuntimeError("boom")
    except Exception:
        print("ignoring")

def test_legit_reraise():
    try:
        raise ValueError("boom")
    except ValueError:
        raise
"""
    analyses = analyze_test_module(code)
    assert len(analyses) == 3
    assert len(analyses[0].swallowed_exceptions) == 1
    assert len(analyses[1].swallowed_exceptions) == 1
    assert len(analyses[2].swallowed_exceptions) == 0


def test_analyze_empty_function():
    code = """
def test_empty_pass():
    pass

def test_empty_docstring():
    \"\"\"TODO: write tests\"\"\"
"""
    analyses = analyze_test_module(code)
    assert len(analyses) == 2
    assert analyses[0].is_empty is True
    assert analyses[1].is_empty is True


def test_analyze_unreachable_assertion():
    code = """
def test_unreachable():
    x = 10
    return
    assert x == 10
"""
    analyses = analyze_test_module(code)
    func = analyses[0]
    assert len(func.unreachable_assertions) == 1


def test_analyze_sut_dependency_chain():
    code = """
from cachetools import LRUCache

def test_lru_dependent():
    cache = LRUCache(maxsize=2)
    cache['a'] = 1
    val = cache['a']
    assert val == 1
    assert cache.currsize == 1

def test_lru_independent():
    cache = LRUCache(maxsize=2)
    cache['a'] = 1
    other = 42
    assert other == 42
"""
    analyses = analyze_test_module(code, target_entrypoint="cachetools.LRUCache")
    assert len(analyses) == 2

    # test_lru_dependent
    dep_func = analyses[0]
    assert "cache" in dep_func.sut_derived_vars or "val" in dep_func.sut_derived_vars
    assert any(a.has_sut_dependency for a in dep_func.assertions)

    # test_lru_independent
    indep_func = analyses[1]
    # In indep_func, the assertion 'assert other == 42' does not depend on cache or val
    assert not any(a.has_sut_dependency for a in indep_func.assertions)


def test_analyze_fully_mocked_sut():
    code = """
from unittest.mock import MagicMock

def test_all_mocked():
    client = MagicMock()
    client.login.return_value = 200
    res = client.login()
    assert res == 200
"""
    analyses = analyze_test_module(code, target_entrypoint="MyClient")
    func = analyses[0]
    assert func.is_fully_mocked is True


def test_sut_tracking_rejects_time_and_stdlib_bypass():
    code = """
import time
import random

def test_time_bypass():
    now = time.time()
    val = random.random()
    assert now > 0
    assert val >= 0
"""
    analyses = analyze_test_module(code, target_entrypoint="cachetools.LRUCache")
    assert len(analyses) == 1
    func = analyses[0]
    assert func.has_real_sut_interaction is False
    assert len(func.sut_calls) == 0
    assert len(func.sut_derived_vars) == 0
    assert not any(a.has_sut_dependency for a in func.assertions)


def test_pytest_raises_without_sut_not_marked_sut():
    code = """
import pytest

def test_manufactured_raise():
    with pytest.raises(ValueError):
        raise ValueError("manufactured")
"""
    analyses = analyze_test_module(code, target_entrypoint="cachetools.LRUCache")
    assert len(analyses) == 1
    func = analyses[0]
    assert func.has_pytest_raises is True
    assert func.has_sut_inside_raises is False
    assert func.has_real_sut_interaction is False


def test_pytest_raises_with_sut_marked_sut():
    code = """
import pytest
from cachetools import LRUCache

def test_real_sut_raise():
    cache = LRUCache(maxsize=2)
    with pytest.raises(KeyError):
        _ = cache["missing"]
"""
    analyses = analyze_test_module(code, target_entrypoint="cachetools.LRUCache")
    assert len(analyses) == 1
    func = analyses[0]
    assert func.has_pytest_raises is True
    assert func.has_sut_inside_raises is True
    assert func.has_real_sut_interaction is True

