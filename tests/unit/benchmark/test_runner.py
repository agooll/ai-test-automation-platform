from pathlib import Path
from unittest.mock import MagicMock
import pytest

from testteller.benchmark.loader import (
    load_all_cases,
    load_all_projects,
    load_benchmark_suite,
)
from testteller.benchmark.runner import BenchmarkRunner
from testteller.benchmark.schema import MutantEvaluationResult


def test_benchmark_runner_suite_execution(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent.parent.parent
    evals_dir = root / "evals"

    projects = load_all_projects(evals_dir / "projects")
    cases = load_all_cases(evals_dir / "cases", base_dir=root, verify_files_exist=True)
    smoke_suite = load_benchmark_suite(evals_dir / "suites" / "smoke_v1.yaml")

    # Mock workflow factory
    def mock_workflow(workspace_dir, framework):
        mock_wf = MagicMock()
        mock_wf.run.return_value = {
            "execution_success": True,
            "execution_result": {"passed": True},
            "repair_round": 1,
            "trace": [
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": False, "duration_ms": 100}}}},
                {"node": "execute", "tools": {"run_tests": {"data": {"passed": True, "duration_ms": 150}}}},
            ],
            "generated_files": {"tests/test_case.py": "# test content"},
        }
        return mock_wf

    # Mock oracle evaluator
    mock_oracle = MagicMock()
    mock_oracle.evaluate.return_value = (
        True,  # clean_passed
        [MutantEvaluationResult("mut-01", detected=True, exit_code=1)],
        True,  # semantic_success
    )

    mock_llm = MagicMock()
    mock_llm.provider = "gemini"
    mock_llm.generation_model = "gemini-2.5-pro"
    mock_llm.client = MagicMock()

    runner = BenchmarkRunner(
        projects=projects,
        cases=cases,
        base_dir=root,
        execution_backend="docker",
        llm_manager=mock_llm,
        oracle_evaluator=mock_oracle,
        workflow_factory=mock_workflow,
    )

    completed_callbacks = []

    def on_complete(run_result):
        completed_callbacks.append(run_result)

    results = runner.run_suite(smoke_suite, repeats=1, on_run_complete=on_complete)

    assert len(results) == 2
    assert len(completed_callbacks) == 2
    assert results[0].case_id == "case_01"
    assert results[1].case_id == "case_13"

    # First execution failed in trace, final passed -> repaired!
    assert results[0].passed_first is False
    assert results[0].passed_final is True
    assert results[0].repaired is True
    assert results[0].repair_rounds == 1
    assert results[0].clean_exec_passed is True
    assert results[0].semantic_success is True
    assert results[0].e2e_duration_ms > 0
    assert results[0].provenance["runner_image"] == "testteller-runner-python:3.11-v1"
    assert "actual_backend" in results[0].provenance
    assert "fallback_used" in results[0].provenance
    assert "testteller_commit" in results[0].provenance
    assert "target_commits" in results[0].provenance


def test_benchmark_runner_formal_benchmark_requires_docker(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent.parent.parent
    evals_dir = root / "evals"

    projects = load_all_projects(evals_dir / "projects")
    cases = load_all_cases(evals_dir / "cases", base_dir=root, verify_files_exist=True)
    formal_suite = load_benchmark_suite(evals_dir / "suites" / "benchmark_v1.yaml")

    runner = BenchmarkRunner(
        projects=projects,
        cases=cases,
        base_dir=root,
        execution_backend="local",
    )

    with pytest.raises(ValueError, match="strictly requires execution_backend='docker'"):
        runner.run_suite(formal_suite, repeats=1)


def test_benchmark_runner_allow_fallback_false_fails_fast(monkeypatch, tmp_path: Path):
    root = Path(__file__).resolve().parent.parent.parent.parent
    evals_dir = root / "evals"

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    projects = load_all_projects(evals_dir / "projects")
    cases = load_all_cases(evals_dir / "cases", base_dir=root, verify_files_exist=True)

    runner = BenchmarkRunner(
        projects=projects,
        cases=cases,
        base_dir=root,
        execution_backend="docker",
        model_name="gemini-2.5-pro",
        allow_fallback=False,
    )

    with pytest.raises(ValueError, match="API key"):
        _ = runner.llm_manager.client

