"""YAML Loaders and Validators for the TestTeller Benchmark Suite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml

from testteller.benchmark.schema import (
    BenchmarkCase,
    BenchmarkSuite,
    MutantSpec,
    ProjectManifest,
)


def _resolve_path(rel_or_abs_path: str, base_dir: Path) -> Path:
    p = Path(rel_or_abs_path)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def load_project_manifest(source: str | Path | dict[str, Any], base_dir: Path | None = None) -> ProjectManifest:
    """Load and validate a ProjectManifest from a YAML file path or dict."""
    if isinstance(source, (str, Path)):
        file_path = Path(source)
        if base_dir and not file_path.is_absolute():
            file_path = (base_dir / file_path).resolve()
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif isinstance(source, dict):
        data = source
    else:
        raise TypeError(f"Expected path or dict for project manifest, got {type(source)}")

    manifest = ProjectManifest(
        name=data.get("name", ""),
        repo_path=data.get("repo_path", ""),
        commit_sha=data.get("commit_sha", ""),
        repo_url=data.get("repo_url"),
        language=data.get("language", "python"),
        test_framework=data.get("test_framework", "pytest"),
        setup_commands=data.get("setup_commands", []),
        target_service=data.get("target_service"),
    )
    manifest.validate()
    return manifest


def load_benchmark_case(
    source: str | Path | dict[str, Any],
    base_dir: Path | None = None,
    verify_files_exist: bool = True,
) -> BenchmarkCase:
    """Load and validate a BenchmarkCase from a YAML file path or dict."""
    if isinstance(source, (str, Path)):
        file_path = Path(source)
        if base_dir and not file_path.is_absolute():
            file_path = (base_dir / file_path).resolve()
        effective_base = file_path.parent if base_dir is None else base_dir
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif isinstance(source, dict):
        data = source
        effective_base = base_dir or Path.cwd()
    else:
        raise TypeError(f"Expected path or dict for benchmark case, got {type(source)}")

    raw_mutants = data.get("mutants", [])
    mutants: list[MutantSpec] = []
    for m in raw_mutants:
        patch_path = m.get("patch_path", "")
        if verify_files_exist and patch_path:
            full_patch = _resolve_path(patch_path, effective_base)
            if not full_patch.exists():
                raise FileNotFoundError(f"Mutant patch file not found: {full_patch} (for mutant '{m.get('mutant_id')}')")
        mutants.append(
            MutantSpec(
                mutant_id=m.get("mutant_id", ""),
                description=m.get("description", ""),
                patch_path=patch_path,
                expected_failed_test_pattern=m.get("expected_failed_test_pattern"),
            )
        )

    req_path = data.get("requirement_path", "")
    if verify_files_exist and req_path:
        full_req = _resolve_path(req_path, effective_base)
        if not full_req.exists():
            raise FileNotFoundError(f"Requirement file not found: {full_req} (for case '{data.get('case_id')}')")

    case = BenchmarkCase(
        case_id=data.get("case_id", ""),
        project_name=data.get("project_name", ""),
        category=data.get("category", ""),
        difficulty=data.get("difficulty", ""),
        split=data.get("split", ""),
        requirement_path=req_path,
        target_entrypoint=data.get("target_entrypoint", ""),
        timeout_sec=int(data.get("timeout_sec", 60)),
        mutants=mutants,
        tags=data.get("tags", []),
    )
    case.validate()
    return case


def load_benchmark_suite(
    source: str | Path | dict[str, Any],
    base_dir: Path | None = None,
) -> BenchmarkSuite:
    """Load and validate a BenchmarkSuite from a YAML file path or dict."""
    if isinstance(source, (str, Path)):
        file_path = Path(source)
        if base_dir and not file_path.is_absolute():
            file_path = (base_dir / file_path).resolve()
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    elif isinstance(source, dict):
        data = source
    else:
        raise TypeError(f"Expected path or dict for benchmark suite, got {type(source)}")

    suite = BenchmarkSuite(
        suite_id=data.get("suite_id", ""),
        description=data.get("description", ""),
        cases=data.get("cases", []),
        default_repeats=int(data.get("default_repeats", 3)),
        default_timeout_sec=int(data.get("default_timeout_sec", 60)),
    )
    suite.validate()
    return suite


def load_all_projects(projects_dir: Path) -> dict[str, ProjectManifest]:
    """Load all project manifests in a directory."""
    projects: dict[str, ProjectManifest] = {}
    if not projects_dir.exists():
        return projects
    for file in sorted(projects_dir.glob("*.yaml")):
        p = load_project_manifest(file)
        projects[p.name] = p
    for file in sorted(projects_dir.glob("*.yml")):
        p = load_project_manifest(file)
        projects[p.name] = p
    return projects


def load_all_cases(cases_dir: Path, base_dir: Path | None = None, verify_files_exist: bool = True) -> dict[str, BenchmarkCase]:
    """Load all benchmark cases in a directory."""
    cases: dict[str, BenchmarkCase] = {}
    if not cases_dir.exists():
        return cases
    for file in sorted(cases_dir.glob("*.yaml")):
        c = load_benchmark_case(file, base_dir=base_dir, verify_files_exist=verify_files_exist)
        cases[c.case_id] = c
    for file in sorted(cases_dir.glob("*.yml")):
        c = load_benchmark_case(file, base_dir=base_dir, verify_files_exist=verify_files_exist)
        cases[c.case_id] = c
    return cases
