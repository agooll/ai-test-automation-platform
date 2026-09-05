import pytest
from testteller.benchmark.schema import (
    BenchmarkCase,
    BenchmarkRunResult,
    BenchmarkSuite,
    BenchmarkSummary,
    MutantEvaluationResult,
    MutantSpec,
    ProjectManifest,
)


def test_project_manifest_validation():
    # Valid 40-char SHA
    p = ProjectManifest(
        name="project-a",
        repo_path="evals/projects/project_a",
        commit_sha="a" * 40,
    )
    p.validate()
    assert p.name == "project-a"

    # Invalid SHA: less than 40 chars
    with pytest.raises(ValueError, match="commit_sha"):
        ProjectManifest(
            name="project-a",
            repo_path="evals/projects/project_a",
            commit_sha="abc123",
        ).validate()

    # Invalid SHA: branch name
    with pytest.raises(ValueError, match="commit_sha"):
        ProjectManifest(
            name="project-a",
            repo_path="evals/projects/project_a",
            commit_sha="main",
        ).validate()


def test_benchmark_case_validation():
    # Valid case
    c = BenchmarkCase(
        case_id="case-001",
        project_name="project-a",
        category="boundary_value",
        difficulty="medium",
        split="dev",
        requirement_path="evals/requirements/req_01.md",
        target_entrypoint="app.main:app",
    )
    c.validate()

    # Invalid category
    with pytest.raises(ValueError, match="category"):
        BenchmarkCase(
            case_id="case-001",
            project_name="project-a",
            category="unknown_category",
            difficulty="medium",
            split="dev",
            requirement_path="evals/requirements/req_01.md",
            target_entrypoint="app.main:app",
        ).validate()

    # Invalid difficulty
    with pytest.raises(ValueError, match="difficulty"):
        BenchmarkCase(
            case_id="case-001",
            project_name="project-a",
            category="happy_path",
            difficulty="extreme",
            split="dev",
            requirement_path="evals/requirements/req_01.md",
            target_entrypoint="app.main:app",
        ).validate()

    # Invalid split
    with pytest.raises(ValueError, match="split"):
        BenchmarkCase(
            case_id="case-001",
            project_name="project-a",
            category="happy_path",
            difficulty="easy",
            split="train",
            requirement_path="evals/requirements/req_01.md",
            target_entrypoint="app.main:app",
        ).validate()


def test_mutant_spec_and_evaluation():
    m = MutantSpec(
        mutant_id="mut-01",
        description="Invert validation logic",
        patch_path="evals/mutants/mut_01.patch",
    )
    m.validate()
    assert m.mutant_id == "mut-01"

    ev = MutantEvaluationResult(mutant_id="mut-01", detected=True, exit_code=1, output_snippet="AssertionError")
    d = ev.as_dict()
    assert d["detected"] is True
    assert d["exit_code"] == 1


def test_benchmark_run_result_and_summary_as_dict():
    run = BenchmarkRunResult(
        case_id="case-001",
        run_index=1,
        passed_first=False,
        passed_final=True,
        repaired=True,
        repair_rounds=1,
        e2e_duration_ms=1234.56,
        clean_exec_passed=True,
        mutant_results=[MutantEvaluationResult("mut-01", True, 1)],
        semantic_success=True,
        failure_type="none",
        provenance={"commit_sha": "a" * 40},
    )
    d = run.as_dict()
    assert d["repaired"] is True
    assert d["semantic_success"] is True

    summary = BenchmarkSummary(
        suite_id="smoke_v1",
        total_cases=1,
        total_runs=1,
        repeats_per_case=1,
        first_pass_rate=0.0,
        final_pass_rate=1.0,
        repair_recovery_rate=1.0,
        repair_uplift=1.0,
        semantic_success_rate=1.0,
        bug_detection_rate=1.0,
        avg_repair_rounds_all=1.0,
        avg_repair_rounds_on_repaired=1.0,
        e2e_latency_p50_ms=1234.56,
        e2e_latency_p95_ms=1234.56,
        sandbox_failure_rate=0.0,
        failure_distribution={},
        provenance={"commit_sha": "a" * 40},
    )
    sd = summary.as_dict()
    assert sd["first_pass_rate"] == 0.0
    assert sd["final_pass_rate"] == 1.0
    assert sd["repair_recovery_rate"] == 1.0
