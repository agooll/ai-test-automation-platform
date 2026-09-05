"""Metrics for comparing baseline generation with the closed-loop agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EvaluationSummary:
    total_runs: int
    first_pass_rate: float
    final_pass_rate: float
    repair_success_rate: float
    average_repair_rounds: float
    average_duration_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "first_pass_rate": round(self.first_pass_rate, 4),
            "final_pass_rate": round(self.final_pass_rate, 4),
            "repair_success_rate": round(self.repair_success_rate, 4),
            "average_repair_rounds": round(self.average_repair_rounds, 4),
            "average_duration_ms": round(self.average_duration_ms, 2),
        }


def summarize_runs(runs: Iterable[dict[str, Any]]) -> EvaluationSummary:
    runs = list(runs)
    if not runs:
        return EvaluationSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    first_pass = 0
    final_pass = 0
    repaired_pass = 0
    rounds = []
    durations = []
    for run in runs:
        events = run.get("trace", [])
        executions = [
            event.get("tools", {}).get("run_tests", {}).get("data", {})
            for event in events if event.get("node") == "execute"
        ]
        if executions and executions[0].get("passed"):
            first_pass += 1
        if run.get("execution_success", run.get("execution_result", {}).get("passed")):
            final_pass += 1
            if executions and not executions[0].get("passed"):
                repaired_pass += 1
        rounds.append(run.get("repair_round", 0))
        durations.extend(item.get("duration_ms", 0.0) for item in executions)
    total = len(runs)
    return EvaluationSummary(
        total_runs=total,
        first_pass_rate=first_pass / total,
        final_pass_rate=final_pass / total,
        repair_success_rate=repaired_pass / total,
        average_repair_rounds=sum(rounds) / total,
        average_duration_ms=sum(durations) / len(durations) if durations else 0.0,
    )
