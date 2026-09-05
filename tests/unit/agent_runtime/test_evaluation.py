from testteller.agent_runtime.evaluation import (
    classify_failure,
    summarize_runs,
)


def test_summarize_runs_distinguishes_first_pass_and_repair():
    runs = [
        {
            "repair_round": 1,
            "execution_result": {"passed": True},
            "trace": [
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": False, "duration_ms": 10}}}},
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": True, "duration_ms": 20}}}},
            ],
        },
        {
            "repair_round": 0,
            "execution_result": {"passed": True},
            "trace": [
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": True, "duration_ms": 15}}}},
            ],
        },
    ]
    summary = summarize_runs(runs)
    assert summary.total_runs == 2
    assert summary.first_pass_rate == 0.5
    assert summary.final_pass_rate == 1.0
    # 1 failed initially, and that 1 was successfully repaired: 1 / 1 = 1.0
    assert summary.repair_recovery_rate == 1.0
    assert summary.repair_success_rate == 1.0  # backward compatibility alias
    assert summary.repair_uplift == 0.5
    assert summary.average_repair_rounds == 0.5
    assert summary.average_repair_rounds_on_repaired == 1.0
    assert summary.e2e_duration_p50_ms == 22.5
    assert summary.failure_distribution == {}


def test_summarize_runs_repair_failure_and_taxonomy():
    runs = [
        # Run 1: first pass
        {
            "repair_round": 0,
            "execution_result": {"passed": True, "duration_ms": 10},
            "trace": [
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": True, "duration_ms": 10}}}},
            ],
        },
        # Run 2: first fail, repair succeeded
        {
            "repair_round": 1,
            "execution_result": {"passed": True, "duration_ms": 20},
            "trace": [
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": False, "duration_ms": 10}}}},
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": True, "duration_ms": 20}}}},
            ],
        },
        # Run 3: first fail, repair failed with timeout
        {
            "repair_round": 2,
            "max_repair_rounds": 2,
            "execution_result": {"passed": False, "timed_out": True, "stdout": "[timeout] killed after 30s", "duration_ms": 30},
            "trace": [
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": False, "duration_ms": 10}}}},
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": False, "duration_ms": 30}}}},
            ],
        },
        # Run 4: first fail, syntax error
        {
            "repair_round": 1,
            "execution_result": {"passed": False, "stderr": "SyntaxError: invalid syntax", "duration_ms": 5},
            "trace": [
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": False, "duration_ms": 5}}}},
            ],
        },
    ]
    summary = summarize_runs(runs)
    assert summary.total_runs == 4
    # 1 first passed, 3 first failed
    assert summary.first_pass_rate == 0.25
    # 2 final passed (Run 1, Run 2)
    assert summary.final_pass_rate == 0.5
    # 3 first failed, 1 recovered -> 1 / 3 = 0.3333...
    assert round(summary.repair_recovery_rate, 4) == 0.3333
    assert round(summary.repair_uplift, 4) == 0.25
    # average repair rounds across all runs: (0 + 1 + 2 + 1) / 4 = 1.0
    assert summary.average_repair_rounds == 1.0
    # average repair rounds on repaired runs: Run 2 has 1 round -> 1.0
    assert summary.average_repair_rounds_on_repaired == 1.0
    assert summary.failure_distribution == {
        "timeout": 1,
        "syntax_error": 1,
    }


def test_classify_failure_taxonomy():
    assert classify_failure({"execution_result": {"passed": True}}) == "none"
    assert classify_failure({"execution_result": {"passed": False, "timed_out": True}}) == "timeout"
    assert classify_failure({"execution_result": {"passed": False, "stderr": "ModuleNotFoundError: No module named 'foo'"}}) == "missing_dependency"
    assert classify_failure({"execution_result": {"passed": False, "stderr": "IndentationError: unexpected indent"}}) == "syntax_error"
    assert classify_failure({"execution_result": {"passed": False, "stdout": "FAILED test.py - AssertionError: 1 != 2"}}) == "assertion_failure"
    assert classify_failure({"execution_result": {"passed": False, "stderr": "requests.exceptions.ConnectionError: Connection refused"}}) == "target_unavailable"
    assert classify_failure({"execution_result": {"passed": False}, "review_verdict": "REJECT"}) == "review_rejected"
    assert classify_failure({"execution_result": {"passed": False}, "repair_round": 2, "max_repair_rounds": 2}) == "repair_exhausted"

