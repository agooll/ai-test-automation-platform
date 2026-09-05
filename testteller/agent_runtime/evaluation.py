"""Metrics for comparing baseline generation with the closed-loop agent."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Sequence


def _percentile(values: Sequence[float], p: float) -> float:
    """Compute standard percentile from a list of numerical values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(math.floor(k))
    c = min(f + 1, len(sorted_vals) - 1)
    d = k - f
    return round(sorted_vals[f] + d * (sorted_vals[c] - sorted_vals[f]), 2)


def classify_failure(run: dict[str, Any]) -> str:
    """Classify failure category according to the Benchmark Failure Taxonomy."""
    # Check if run passed
    if run.get("execution_success", run.get("execution_result", {}).get("passed")):
        return "none"

    exec_res = run.get("execution_result", {})
    stderr = (exec_res.get("stderr") or "").lower()
    stdout = (exec_res.get("stdout") or "").lower()
    combined = f"{stdout} {stderr}"

    if exec_res.get("timed_out") or "[timeout]" in combined:
        return "timeout"
    if "modulenotfounderror" in combined or "no module named" in combined:
        return "missing_dependency"
    if "syntaxerror" in combined or "indentationerror" in combined:
        return "syntax_error"
    if "assertionerror" in combined or "assert " in combined or "failed" in combined:
        return "assertion_failure"
    if "connection refused" in combined or "network is unreachable" in combined:
        return "target_unavailable"
    if run.get("quality_gate_rejected") or run.get("review_verdict") == "REJECT":
        return "review_rejected"
    if run.get("repair_round", 0) >= run.get("max_repair_rounds", 2):
        return "repair_exhausted"
    return "runtime_or_environment_failure"


@dataclass(frozen=True)
class EvaluationSummary:
    total_runs: int
    first_pass_rate: float
    final_pass_rate: float
    repair_recovery_rate: float
    repair_uplift: float
    average_repair_rounds: float
    average_repair_rounds_on_repaired: float
    average_duration_ms: float
    e2e_duration_p50_ms: float = 0.0
    e2e_duration_p95_ms: float = 0.0
    execution_duration_p50_ms: float = 0.0
    execution_duration_p95_ms: float = 0.0
    failure_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def repair_success_rate(self) -> float:
        """Backward compatibility alias for repair_recovery_rate."""
        return self.repair_recovery_rate

    @property
    def average_repair_rounds_all(self) -> float:
        """Alias for average_repair_rounds across all runs."""
        return self.average_repair_rounds

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "first_pass_rate": round(self.first_pass_rate, 4),
            "final_pass_rate": round(self.final_pass_rate, 4),
            "repair_recovery_rate": round(self.repair_recovery_rate, 4),
            "repair_uplift": round(self.repair_uplift, 4),
            "repair_success_rate": round(self.repair_success_rate, 4),
            "average_repair_rounds": round(self.average_repair_rounds, 4),
            "average_repair_rounds_all": round(self.average_repair_rounds_all, 4),
            "average_repair_rounds_on_repaired": round(self.average_repair_rounds_on_repaired, 4),
            "average_duration_ms": round(self.average_duration_ms, 2),
            "e2e_duration_p50_ms": self.e2e_duration_p50_ms,
            "e2e_duration_p95_ms": self.e2e_duration_p95_ms,
            "execution_duration_p50_ms": self.execution_duration_p50_ms,
            "execution_duration_p95_ms": self.execution_duration_p95_ms,
            "failure_distribution": self.failure_distribution,
        }


def summarize_runs(runs: Iterable[dict[str, Any]]) -> EvaluationSummary:
    runs = list(runs)
    if not runs:
        return EvaluationSummary(
            total_runs=0,
            first_pass_rate=0.0,
            final_pass_rate=0.0,
            repair_recovery_rate=0.0,
            repair_uplift=0.0,
            average_repair_rounds=0.0,
            average_repair_rounds_on_repaired=0.0,
            average_duration_ms=0.0,
        )

    first_pass = 0
    first_fail = 0
    final_pass = 0
    first_fail_and_final_pass = 0

    all_rounds = []
    repaired_rounds = []
    execution_durations = []
    e2e_durations = []
    failure_counts: dict[str, int] = {}

    for run in runs:
        events = run.get("trace", [])
        executions = [
            event.get("tools", {}).get("run_tests", {}).get("data", {})
            for event in events if event.get("node") == "execute"
        ]

        first_exec_passed = bool(executions and executions[0].get("passed"))
        final_exec_passed = bool(run.get("execution_success", run.get("execution_result", {}).get("passed")))

        if first_exec_passed:
            first_pass += 1
        else:
            first_fail += 1

        if final_exec_passed:
            final_pass += 1
            if not first_exec_passed:
                first_fail_and_final_pass += 1

        rounds = run.get("repair_round", 0)
        all_rounds.append(rounds)
        if not first_exec_passed and final_exec_passed:
            repaired_rounds.append(rounds)

        exec_ms = [item.get("duration_ms", 0.0) for item in executions]
        execution_durations.extend(exec_ms)

        e2e_ms = run.get("e2e_duration_ms")
        if e2e_ms is not None:
            e2e_durations.append(float(e2e_ms))
        elif exec_ms:
            e2e_durations.append(sum(exec_ms))

        category = classify_failure(run)
        if category != "none":
            failure_counts[category] = failure_counts.get(category, 0) + 1

    total = len(runs)
    first_pass_rate = first_pass / total
    final_pass_rate = final_pass / total
    repair_recovery_rate = (first_fail_and_final_pass / first_fail) if first_fail > 0 else 0.0
    repair_uplift = final_pass_rate - first_pass_rate

    avg_rounds_all = sum(all_rounds) / total
    avg_rounds_repaired = (sum(repaired_rounds) / len(repaired_rounds)) if repaired_rounds else 0.0
    avg_duration = sum(execution_durations) / len(execution_durations) if execution_durations else 0.0

    return EvaluationSummary(
        total_runs=total,
        first_pass_rate=first_pass_rate,
        final_pass_rate=final_pass_rate,
        repair_recovery_rate=repair_recovery_rate,
        repair_uplift=repair_uplift,
        average_repair_rounds=avg_rounds_all,
        average_repair_rounds_on_repaired=avg_rounds_repaired,
        average_duration_ms=avg_duration,
        e2e_duration_p50_ms=_percentile(e2e_durations, 50.0),
        e2e_duration_p95_ms=_percentile(e2e_durations, 95.0),
        execution_duration_p50_ms=_percentile(execution_durations, 50.0),
        execution_duration_p95_ms=_percentile(execution_durations, 95.0),
        failure_distribution=failure_counts,
    )

