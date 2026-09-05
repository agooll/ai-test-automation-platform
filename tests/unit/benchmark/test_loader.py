from pathlib import Path
import pytest
import yaml

from testteller.benchmark.loader import (
    load_all_cases,
    load_all_projects,
    load_benchmark_case,
    load_benchmark_suite,
    load_project_manifest,
)


def test_load_project_manifest(tmp_path: Path):
    proj_file = tmp_path / "project_a.yaml"
    proj_data = {
        "name": "sample-project-a",
        "repo_path": str(tmp_path),
        "commit_sha": "b" * 40,
        "language": "python",
        "test_framework": "pytest",
    }
    proj_file.write_text(yaml.dump(proj_data), encoding="utf-8")

    manifest = load_project_manifest(proj_file)
    assert manifest.name == "sample-project-a"
    assert manifest.commit_sha == "b" * 40


def test_load_benchmark_case_validates_file_existence(tmp_path: Path):
    req_file = tmp_path / "req_01.md"
    req_file.write_text("Requirement: User registration", encoding="utf-8")

    patch_file = tmp_path / "mut_01.patch"
    patch_file.write_text("--- a/app.py\n+++ b/app.py\n", encoding="utf-8")

    case_file = tmp_path / "case_01.yaml"
    case_data = {
        "case_id": "case-01",
        "project_name": "sample-project-a",
        "category": "happy_path",
        "difficulty": "easy",
        "split": "dev",
        "requirement_path": str(req_file),
        "target_entrypoint": "app.auth:register",
        "mutants": [
            {
                "mutant_id": "mut-01",
                "description": "Bypass email check",
                "patch_path": str(patch_file),
            }
        ],
    }
    case_file.write_text(yaml.dump(case_data), encoding="utf-8")

    case = load_benchmark_case(case_file, verify_files_exist=True)
    assert case.case_id == "case-01"
    assert len(case.mutants) == 1

    # Now test missing requirement file raises FileNotFoundError
    case_data_missing_req = dict(case_data)
    case_data_missing_req["requirement_path"] = str(tmp_path / "nonexistent.md")
    case_missing_file = tmp_path / "case_missing.yaml"
    case_missing_file.write_text(yaml.dump(case_data_missing_req), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Requirement file not found"):
        load_benchmark_case(case_missing_file, verify_files_exist=True)


def test_load_benchmark_suite(tmp_path: Path):
    suite_file = tmp_path / "smoke_v1.yaml"
    suite_data = {
        "suite_id": "smoke_v1",
        "description": "Smoke evaluation suite",
        "cases": ["case-01", "case-02"],
        "default_repeats": 2,
    }
    suite_file.write_text(yaml.dump(suite_data), encoding="utf-8")

    suite = load_benchmark_suite(suite_file)
    assert suite.suite_id == "smoke_v1"
    assert suite.cases == ["case-01", "case-02"]
    assert suite.default_repeats == 2


def test_load_real_benchmark_dataset():
    root = Path(__file__).resolve().parent.parent.parent.parent
    evals_dir = root / "evals"

    # 1. Projects
    projects = load_all_projects(evals_dir / "projects")
    assert "oss_project_1" in projects
    assert "oss_project_2" in projects

    fixtures = load_all_projects(evals_dir / "projects" / "fixtures")
    assert "project_a" in fixtures
    assert "project_b" in fixtures

    # 2. Cases
    cases = load_all_cases(evals_dir / "cases", base_dir=root, verify_files_exist=True)
    assert len(cases) == 24

    # Check stratification
    dev_cases = [c for c in cases.values() if c.split == "dev"]
    holdout_cases = [c for c in cases.values() if c.split == "holdout"]
    assert len(dev_cases) == 16
    assert len(holdout_cases) == 8

    # 3. Suites
    smoke = load_benchmark_suite(evals_dir / "suites" / "smoke_v1.yaml")
    assert len(smoke.cases) == 2

    benchmark_v1 = load_benchmark_suite(evals_dir / "suites" / "benchmark_v1.yaml")
    assert len(benchmark_v1.cases) == 24

