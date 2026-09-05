from testteller.agent_runtime.evaluation import summarize_runs


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
    assert summary.first_pass_rate == 0.5
    assert summary.final_pass_rate == 1.0
    assert summary.repair_success_rate == 0.5
    assert summary.average_repair_rounds == 0.5
