from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from testteller.benchmark.cli import benchmark_command


def test_benchmark_cli_suite_not_found():
    code = benchmark_command(suite="nonexistent_suite.yaml")
    assert code == 1


def test_benchmark_cli_execution_flow(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent.parent.parent

    mock_run_res = MagicMock()
    mock_run_res.case_id = "case_01"
    mock_run_res.run_index = 1
    mock_run_res.passed_final = True
    mock_run_res.semantic_success = True
    mock_run_res.repaired = False
    mock_run_res.repair_rounds = 0
    mock_run_res.e2e_duration_ms = 500.0

    mock_summary = MagicMock()
    mock_summary.suite_id = "smoke_v1"
    mock_summary.total_cases = 1
    mock_summary.total_runs = 1
    mock_summary.repeats_per_case = 1
    mock_summary.first_pass_rate = 1.0
    mock_summary.final_pass_rate = 1.0
    mock_summary.repair_recovery_rate = 0.0
    mock_summary.repair_uplift = 0.0
    mock_summary.semantic_success_rate = 1.0
    mock_summary.bug_detection_rate = 1.0
    mock_summary.avg_repair_rounds_all = 0.0
    mock_summary.avg_repair_rounds_on_repaired = 0.0
    mock_summary.e2e_latency_p50_ms = 500.0
    mock_summary.e2e_latency_p95_ms = 500.0
    mock_summary.sandbox_failure_rate = 0.0

    with patch("testteller.benchmark.cli.BenchmarkRunner") as MockRunner, \
         patch("testteller.benchmark.cli.aggregate_benchmark_runs", return_value=mock_summary), \
         patch("testteller.benchmark.cli.BenchmarkReporter") as MockReporter:

        runner_inst = MockRunner.return_value
        runner_inst.run_suite.side_effect = lambda suite, repeats, on_run_complete: [
            on_run_complete(mock_run_res) or mock_run_res
        ]

        reporter_inst = MockReporter.return_value
        reporter_inst.write_all.return_value = {
            "summary_json": tmp_path / "summary.json",
            "runs_jsonl": tmp_path / "runs.jsonl",
            "report_md": tmp_path / "report.md",
        }

        code = benchmark_command(
            suite="smoke_v1",
            repeats=1,
            backend="docker",
            output_dir=str(tmp_path),
        )

        assert code == 0
        assert runner_inst.run_suite.called
        assert reporter_inst.write_all.called


def test_benchmark_cli_formal_benchmark_requires_docker(tmp_path: Path):
    """Verify CLI immediately rejects formal benchmark_v1 with backend='local'."""
    code = benchmark_command(
        suite="benchmark_v1",
        repeats=1,
        backend="local",
        output_dir=str(tmp_path),
    )
    assert code == 1

