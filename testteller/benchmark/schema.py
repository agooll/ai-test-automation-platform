"""Data models and schemas for the TestTeller Benchmark Suite."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

VALID_CATEGORIES = {
    "happy_path",
    "boundary_value",
    "error_handling",
    "concurrency_state",
    "mock_contract",
    "security_injection",
}

VALID_DIFFICULTIES = {"easy", "medium", "hard"}

VALID_SPLITS = {"dev", "holdout"}

COMMIT_SHA_REGEX = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class ProjectManifest:
    """Represents an immutable, version-pinned project under evaluation."""

    name: str
    repo_path: str
    commit_sha: str
    repo_url: str | None = None
    language: str = "python"
    test_framework: str = "pytest"
    setup_commands: list[str] = field(default_factory=list)
    target_service: dict[str, Any] | None = None

    def validate(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("ProjectManifest: 'name' must be a non-empty string.")
        if not self.repo_path:
            raise ValueError(f"ProjectManifest({self.name}): 'repo_path' is required.")
        if not COMMIT_SHA_REGEX.match(self.commit_sha):
            raise ValueError(
                f"ProjectManifest({self.name}): 'commit_sha' must be a 40-character hex string (got '{self.commit_sha}')."
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MutantSpec:
    """Specification of a seeded defect (bug/mutant) to evaluate oracle quality."""

    mutant_id: str
    description: str
    patch_path: str
    expected_failed_test_pattern: str | None = None

    def validate(self) -> None:
        if not self.mutant_id or not self.mutant_id.strip():
            raise ValueError("MutantSpec: 'mutant_id' must be non-empty.")
        if not self.patch_path or not self.patch_path.strip():
            raise ValueError(f"MutantSpec({self.mutant_id}): 'patch_path' is required.")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkCase:
    """Definition of a single evaluation case."""

    case_id: str
    project_name: str
    category: str
    difficulty: str
    split: str
    requirement_path: str
    target_entrypoint: str
    timeout_sec: int = 60
    mutants: list[MutantSpec] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.case_id or not self.case_id.strip():
            raise ValueError("BenchmarkCase: 'case_id' must be non-empty.")
        if not self.project_name or not self.project_name.strip():
            raise ValueError(f"BenchmarkCase({self.case_id}): 'project_name' is required.")
        if self.category not in VALID_CATEGORIES:
            raise ValueError(
                f"BenchmarkCase({self.case_id}): invalid category '{self.category}'. Must be one of {sorted(VALID_CATEGORIES)}."
            )
        if self.difficulty not in VALID_DIFFICULTIES:
            raise ValueError(
                f"BenchmarkCase({self.case_id}): invalid difficulty '{self.difficulty}'. Must be one of {sorted(VALID_DIFFICULTIES)}."
            )
        if self.split not in VALID_SPLITS:
            raise ValueError(
                f"BenchmarkCase({self.case_id}): invalid split '{self.split}'. Must be one of {sorted(VALID_SPLITS)}."
            )
        if not self.requirement_path:
            raise ValueError(f"BenchmarkCase({self.case_id}): 'requirement_path' is required.")
        if self.timeout_sec <= 0:
            raise ValueError(f"BenchmarkCase({self.case_id}): 'timeout_sec' must be positive.")
        for mutant in self.mutants:
            mutant.validate()

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "project_name": self.project_name,
            "category": self.category,
            "difficulty": self.difficulty,
            "split": self.split,
            "requirement_path": self.requirement_path,
            "target_entrypoint": self.target_entrypoint,
            "timeout_sec": self.timeout_sec,
            "mutants": [m.as_dict() for m in self.mutants],
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class BenchmarkSuite:
    """Definition of a benchmark suite containing multiple benchmark cases."""

    suite_id: str
    description: str
    cases: list[str]
    default_repeats: int = 3
    default_timeout_sec: int = 60

    def validate(self) -> None:
        if not self.suite_id or not self.suite_id.strip():
            raise ValueError("BenchmarkSuite: 'suite_id' must be non-empty.")
        if not self.cases:
            raise ValueError(f"BenchmarkSuite({self.suite_id}): 'cases' must not be empty.")
        if self.default_repeats <= 0:
            raise ValueError(f"BenchmarkSuite({self.suite_id}): 'default_repeats' must be positive.")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MutantEvaluationResult:
    """Result of running generated tests against a seeded mutant."""

    mutant_id: str
    detected: bool
    exit_code: int
    output_snippet: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkRunResult:
    """Detailed execution result for a single run of a benchmark case."""

    case_id: str
    run_index: int
    passed_first: bool
    passed_final: bool
    repaired: bool
    repair_rounds: int
    e2e_duration_ms: float
    clean_exec_passed: bool
    mutant_results: list[MutantEvaluationResult] = field(default_factory=list)
    semantic_success: bool = False
    failure_type: str = "none"
    provenance: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "run_index": self.run_index,
            "passed_first": self.passed_first,
            "passed_final": self.passed_final,
            "repaired": self.repaired,
            "repair_rounds": self.repair_rounds,
            "e2e_duration_ms": round(self.e2e_duration_ms, 2),
            "clean_exec_passed": self.clean_exec_passed,
            "mutant_results": [m.as_dict() for m in self.mutant_results],
            "semantic_success": self.semantic_success,
            "failure_type": self.failure_type,
            "provenance": self.provenance,
            "trace": self.trace,
            "generated_files": self.generated_files,
        }


@dataclass(frozen=True)
class BenchmarkSummary:
    """Comprehensive evaluation summary answering the 6 benchmark questions."""

    suite_id: str
    total_cases: int
    total_runs: int
    repeats_per_case: int
    first_pass_rate: float
    final_pass_rate: float
    repair_recovery_rate: float
    repair_uplift: float
    semantic_success_rate: float
    bug_detection_rate: float
    avg_repair_rounds_all: float
    avg_repair_rounds_on_repaired: float
    e2e_latency_p50_ms: float
    e2e_latency_p95_ms: float
    sandbox_failure_rate: float
    failure_distribution: dict[str, int] = field(default_factory=dict)
    category_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    difficulty_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "total_cases": self.total_cases,
            "total_runs": self.total_runs,
            "repeats_per_case": self.repeats_per_case,
            "first_pass_rate": round(self.first_pass_rate, 4),
            "final_pass_rate": round(self.final_pass_rate, 4),
            "repair_recovery_rate": round(self.repair_recovery_rate, 4),
            "repair_uplift": round(self.repair_uplift, 4),
            "semantic_success_rate": round(self.semantic_success_rate, 4),
            "bug_detection_rate": round(self.bug_detection_rate, 4),
            "avg_repair_rounds_all": round(self.avg_repair_rounds_all, 4),
            "avg_repair_rounds_on_repaired": round(self.avg_repair_rounds_on_repaired, 4),
            "e2e_latency_p50_ms": round(self.e2e_latency_p50_ms, 2),
            "e2e_latency_p95_ms": round(self.e2e_latency_p95_ms, 2),
            "sandbox_failure_rate": round(self.sandbox_failure_rate, 4),
            "failure_distribution": self.failure_distribution,
            "category_metrics": self.category_metrics,
            "difficulty_metrics": self.difficulty_metrics,
            "provenance": self.provenance,
        }
