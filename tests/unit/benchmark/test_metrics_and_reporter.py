import json
from pathlib import Path
import pytest

from testteller.benchmark.metrics import aggregate_benchmark_runs
from testteller.benchmark.reporter import BenchmarkReporter
from testteller.benchmark.schema import (
    BenchmarkCase,
    BenchmarkRunResult,
    MutantEvaluationResult,
)


def test_aggregate_benchmark_runs_and_reporter(tmp_path: Path):
    cases = {
        "case-01": BenchmarkCase(
            case_id="case-01",
            project_name="project_a",
            category="happy_path",
            difficulty="easy",
            split="dev",
            requirement_path="req_01.md",
            target_entrypoint="app.main",
        ),
        "case-02": BenchmarkCase(
            case_id="case-02",
            project_name="project_b",
            category="error_handling",
            difficulty="hard",
            split="holdout",
            requirement_path="req_02.md",
            target_entrypoint="processor.main",
        ),
    }

    # Run 1: case-01, passed first try, clean passed, 1 mutant detected -> semantic success
    run1 = BenchmarkRunResult(
        case_id="case-01",
        run_index=1,
        passed_first=True,
        passed_final=True,
        repaired=False,
        repair_rounds=0,
        e2e_duration_ms=1000.0,
        clean_exec_passed=True,
        mutant_results=[MutantEvaluationResult("mut-01", detected=True, exit_code=1)],
        semantic_success=True,
        failure_type="none",
        provenance={"commit_sha": "a" * 40, "model": "gemini-2.5-pro"},
    )

    # Run 2: case-02, first failed, repaired after 2 rounds, clean passed, 1 mutant detected -> semantic success
    run2 = BenchmarkRunResult(
        case_id="case-02",
        run_index=1,
        passed_first=False,
        passed_final=True,
        repaired=True,
        repair_rounds=2,
        e2e_duration_ms=3000.0,
        clean_exec_passed=True,
        mutant_results=[MutantEvaluationResult("mut-02", detected=True, exit_code=1)],
        semantic_success=True,
        failure_type="none",
        provenance={"commit_sha": "a" * 40, "model": "gemini-2.5-pro"},
    )

    # Run 3: case-02, first failed, repair failed (timeout)
    run3 = BenchmarkRunResult(
        case_id="case-02",
        run_index=2,
        passed_first=False,
        passed_final=False,
        repaired=False,
        repair_rounds=2,
        e2e_duration_ms=4000.0,
        clean_exec_passed=False,
        mutant_results=[],
        semantic_success=False,
        failure_type="timeout",
        provenance={"commit_sha": "a" * 40, "model": "gemini-2.5-pro"},
    )

    runs = [run1, run2, run3]
    summary = aggregate_benchmark_runs("test_suite", cases, runs, repeats_per_case=2)

    assert summary.total_cases == 2
    assert summary.total_runs == 3
    # First pass: run1 (1/3 = 0.3333)
    assert round(summary.first_pass_rate, 4) == 0.3333
    # Final pass: run1, run2 (2/3 = 0.6667)
    assert round(summary.final_pass_rate, 4) == 0.6667
    # First fail: run2, run3 (2). Repaired: run2 (1). Recovery rate = 1 / 2 = 0.5
    assert summary.repair_recovery_rate == 0.5
    # Uplift = 0.6667 - 0.3333 = 0.3333
    assert round(summary.repair_uplift, 4) == 0.3333
    # Semantic success: run1, run2 (2/3)
    assert round(summary.semantic_success_rate, 4) == 0.6667
    # Bug detection rate: mut-01 detected, mut-02 detected -> 2/2 = 1.0
    assert summary.bug_detection_rate == 1.0
    # Average repair rounds all: (0 + 2 + 2) / 3 = 1.3333
    assert round(summary.avg_repair_rounds_all, 4) == 1.3333
    # Average repair rounds on repaired: run2 took 2 rounds -> 2.0
    assert summary.avg_repair_rounds_on_repaired == 2.0
    # Failure taxonomy
    assert summary.failure_distribution == {"timeout": 1}
    assert round(summary.sandbox_failure_rate, 4) == 0.3333

    # Check reporter
    reporter = BenchmarkReporter(tmp_path / "reports")
    paths = reporter.write_all(summary, runs)

    assert paths["summary_json"].exists()
    assert paths["runs_jsonl"].exists()
    assert paths["report_md"].exists()

    # Verify JSON content
    with open(paths["summary_json"], encoding="utf-8") as f:
        data = json.load(f)
        assert data["suite_id"] == "test_suite"
        assert data["first_pass_rate"] == 0.3333

    # Verify JSONL lines
    lines = paths["runs_jsonl"].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3

    # Verify Markdown report
    md_content = paths["report_md"].read_text(encoding="utf-8")
    assert "# TestTeller Benchmark Report: test_suite" in md_content
    assert "First Execution Pass Rate" in md_content
    assert "Repair Recovery Rate" in md_content
    assert "Dual-Oracle Semantic Success" in md_content
    assert "`timeout`" in md_content


def test_aggregate_multi_project_provenance():
    """Verify that summary aggregates target commits, corpus hashes, and projects across all runs."""
    cases = {}
    run1 = BenchmarkRunResult(
        case_id="case-01",
        run_index=1,
        passed_first=True,
        passed_final=True,
        repaired=False,
        repair_rounds=0,
        e2e_duration_ms=100.0,
        clean_exec_passed=True,
        mutant_results=[],
        semantic_success=True,
        failure_type="none",
        provenance={
            "project_name": "oss_project_1",
            "commit_sha": "1111111111111111111111111111111111111111",
            "target_commits": {"oss_project_1": "1111111111111111111111111111111111111111"},
            "corpus_hashes": {"oss_project_1": "hash1"},
            "actual_backend": "docker",
            "actual_runner_image": "testteller-runner-python:3.11-v1",
            "actual_runner_digest": "sha256:abc12345",
            "actual_model_provider": "gemini",
            "actual_model_name": "gemini-2.5-pro",
            "fallback_used": False,
        },
    )
    run2 = BenchmarkRunResult(
        case_id="case-13",
        run_index=1,
        passed_first=True,
        passed_final=True,
        repaired=False,
        repair_rounds=0,
        e2e_duration_ms=200.0,
        clean_exec_passed=True,
        mutant_results=[],
        semantic_success=True,
        failure_type="none",
        provenance={
            "project_name": "oss_project_2",
            "commit_sha": "2222222222222222222222222222222222222222",
            "target_commits": {"oss_project_2": "2222222222222222222222222222222222222222"},
            "corpus_hashes": {"oss_project_2": "hash2"},
            "actual_backend": "docker",
            "actual_runner_image": "testteller-runner-python:3.11-v1",
            "actual_runner_digest": "sha256:abc12345",
            "actual_model_provider": "gemini",
            "actual_model_name": "gemini-2.5-pro",
            "fallback_used": False,
        },
    )
    summary = aggregate_benchmark_runs("multi_proj", cases, [run1, run2], repeats_per_case=1)
    prov = summary.provenance
    assert set(prov["projects"]) == {"oss_project_1", "oss_project_2"}
    assert "oss_project_1" in prov["target_commits"]
    assert "oss_project_2" in prov["target_commits"]
    assert "oss_project_1" in prov["corpus_hashes"]
    assert "oss_project_2" in prov["corpus_hashes"]
    assert prov["fallback_used"] is False
    assert prov["actual_backend"] == "docker"
    assert prov["actual_runner_digest"] == "sha256:abc12345"

