"""Metrics aggregation engine for the TestTeller Benchmark Suite."""

from __future__ import annotations

import math
from typing import Any, Sequence

from testteller.agent_runtime.evaluation import _percentile
from testteller.benchmark.schema import BenchmarkCase, BenchmarkRunResult, BenchmarkSummary


def aggregate_benchmark_runs(
    suite_id: str,
    cases: dict[str, BenchmarkCase],
    runs: Sequence[BenchmarkRunResult],
    repeats_per_case: int = 1,
) -> BenchmarkSummary:
    """Compute comprehensive benchmark metrics answering the 6 core evaluation questions."""
    total_runs = len(runs)
    if total_runs == 0:
        return BenchmarkSummary(
            suite_id=suite_id,
            total_cases=0,
            total_runs=0,
            repeats_per_case=repeats_per_case,
            first_pass_rate=0.0,
            final_pass_rate=0.0,
            repair_recovery_rate=0.0,
            repair_uplift=0.0,
            semantic_success_rate=0.0,
            bug_detection_rate=0.0,
            avg_repair_rounds_all=0.0,
            avg_repair_rounds_on_repaired=0.0,
            e2e_latency_p50_ms=0.0,
            e2e_latency_p95_ms=0.0,
            sandbox_failure_rate=0.0,
        )

    unique_cases = set(r.case_id for r in runs)
    first_pass_count = 0
    first_fail_count = 0
    final_pass_count = 0
    first_fail_and_final_pass_count = 0
    semantic_success_count = 0

    total_mutants = 0
    detected_mutants = 0

    all_repair_rounds: list[int] = []
    repaired_repair_rounds: list[int] = []
    latencies: list[float] = []

    sandbox_failures = 0
    failure_dist: dict[str, int] = {}

    # Breakdowns
    category_runs: dict[str, list[BenchmarkRunResult]] = {}
    difficulty_runs: dict[str, list[BenchmarkRunResult]] = {}

    # Aggregate multi-project provenance across all runs
    all_projects: set[str] = set()
    target_commits: dict[str, str] = {}
    corpus_hashes: dict[str, str] = {}
    rag_collections: set[str] = set()
    backends_used: set[str] = set()
    runner_images_used: set[str] = set()
    runner_digests_used: set[str] = set()
    models_used: set[str] = set()
    providers_used: set[str] = set()
    testteller_commit: str | None = None
    fallback_used_overall: bool = False

    for run in runs:
        prov = run.provenance or {}
        p_name = prov.get("project_name")
        if p_name:
            all_projects.add(p_name)
        if prov.get("target_commits"):
            target_commits.update(prov["target_commits"])
        elif p_name and prov.get("commit_sha"):
            target_commits[p_name] = prov["commit_sha"]

        if prov.get("corpus_hashes"):
            corpus_hashes.update(prov["corpus_hashes"])
        elif p_name and prov.get("corpus_hash"):
            corpus_hashes[p_name] = prov["corpus_hash"]

        if prov.get("rag_collection"):
            rag_collections.add(prov["rag_collection"])
        if prov.get("actual_backend"):
            backends_used.add(prov["actual_backend"])
        if prov.get("actual_runner_image"):
            runner_images_used.add(prov["actual_runner_image"])
        if prov.get("actual_runner_digest"):
            runner_digests_used.add(prov["actual_runner_digest"])
        if prov.get("actual_model_name"):
            models_used.add(prov["actual_model_name"])
        if prov.get("actual_model_provider"):
            providers_used.add(prov["actual_model_provider"])
        if prov.get("testteller_commit") and not testteller_commit:
            testteller_commit = prov["testteller_commit"]
        if prov.get("fallback_used"):
            fallback_used_overall = True

    provenance_meta = {
        "projects": sorted(list(all_projects)),
        "target_commits": target_commits,
        "corpus_hashes": corpus_hashes,
        "testteller_commit": testteller_commit,
        "actual_backends": sorted(list(backends_used)),
        "actual_backend": list(backends_used)[0] if len(backends_used) == 1 else (", ".join(sorted(backends_used)) if backends_used else "unknown"),
        "actual_runner_images": sorted(list(runner_images_used)),
        "actual_runner_image": list(runner_images_used)[0] if len(runner_images_used) == 1 else (None if not runner_images_used else ", ".join(sorted(runner_images_used))),
        "actual_runner_digests": sorted(list(runner_digests_used)),
        "actual_runner_digest": list(runner_digests_used)[0] if len(runner_digests_used) == 1 else (None if not runner_digests_used else ", ".join(sorted(runner_digests_used))),
        "actual_model_providers": sorted(list(providers_used)),
        "actual_model_provider": list(providers_used)[0] if len(providers_used) == 1 else (", ".join(sorted(providers_used)) if providers_used else "unknown"),
        "actual_model_names": sorted(list(models_used)),
        "actual_model_name": list(models_used)[0] if len(models_used) == 1 else (", ".join(sorted(models_used)) if models_used else "unknown"),
        "fallback_used": fallback_used_overall,
        "rag_collections": sorted(list(rag_collections)),
        # Backward compatibility aliases
        "project_name": ", ".join(sorted(all_projects)) if all_projects else "unknown",
        "commit_sha": ", ".join(f"{k}@{v[:8]}" for k, v in sorted(target_commits.items())) if target_commits else "",
        "runner_image": list(runner_images_used)[0] if len(runner_images_used) == 1 else (None if not runner_images_used else ", ".join(sorted(runner_images_used))),
        "model_name": list(models_used)[0] if len(models_used) == 1 else (", ".join(sorted(models_used)) if models_used else "unknown"),
        "corpus_hash": ", ".join(f"{k}:{v[:8]}" for k, v in sorted(corpus_hashes.items())) if corpus_hashes else "",
    }

    for run in runs:
        latencies.append(run.e2e_duration_ms)
        all_repair_rounds.append(run.repair_rounds)

        if run.passed_first:
            first_pass_count += 1
        else:
            first_fail_count += 1

        if run.passed_final:
            final_pass_count += 1
            if not run.passed_first:
                first_fail_and_final_pass_count += 1
                repaired_repair_rounds.append(run.repair_rounds)

        if run.semantic_success:
            semantic_success_count += 1

        for m_res in run.mutant_results:
            total_mutants += 1
            if m_res.detected:
                detected_mutants += 1

        if run.failure_type != "none":
            failure_dist[run.failure_type] = failure_dist.get(run.failure_type, 0) + 1
            if run.failure_type in {"runtime_or_environment_failure", "timeout"}:
                sandbox_failures += 1

        # Grouping by category & difficulty
        case_def = cases.get(run.case_id)
        if case_def:
            category_runs.setdefault(case_def.category, []).append(run)
            difficulty_runs.setdefault(case_def.difficulty, []).append(run)

    first_pass_rate = first_pass_count / total_runs
    final_pass_rate = final_pass_count / total_runs
    repair_recovery_rate = (
        first_fail_and_final_pass_count / first_fail_count if first_fail_count > 0 else 0.0
    )
    repair_uplift = final_pass_rate - first_pass_rate
    semantic_success_rate = semantic_success_count / total_runs
    bug_detection_rate = (
        detected_mutants / total_mutants if total_mutants > 0 else (1.0 if final_pass_count > 0 else 0.0)
    )

    avg_rounds_all = sum(all_repair_rounds) / total_runs if total_runs > 0 else 0.0
    avg_rounds_repaired = (
        sum(repaired_repair_rounds) / len(repaired_repair_rounds) if repaired_repair_rounds else 0.0
    )

    p50_lat = _percentile(latencies, 50.0)
    p95_lat = _percentile(latencies, 95.0)
    sandbox_failure_rate = sandbox_failures / total_runs

    def compute_group_metrics(group_dict: dict[str, list[BenchmarkRunResult]]) -> dict[str, dict[str, float]]:
        metrics: dict[str, dict[str, float]] = {}
        for group_name, g_runs in group_dict.items():
            g_total = len(g_runs)
            g_first = sum(1 for r in g_runs if r.passed_first) / g_total if g_total else 0.0
            g_final = sum(1 for r in g_runs if r.passed_final) / g_total if g_total else 0.0
            g_sem = sum(1 for r in g_runs if r.semantic_success) / g_total if g_total else 0.0
            metrics[group_name] = {
                "total_runs": g_total,
                "first_pass_rate": round(g_first, 4),
                "final_pass_rate": round(g_final, 4),
                "semantic_success_rate": round(g_sem, 4),
            }
        return metrics

    return BenchmarkSummary(
        suite_id=suite_id,
        total_cases=len(unique_cases),
        total_runs=total_runs,
        repeats_per_case=repeats_per_case,
        first_pass_rate=first_pass_rate,
        final_pass_rate=final_pass_rate,
        repair_recovery_rate=repair_recovery_rate,
        repair_uplift=repair_uplift,
        semantic_success_rate=semantic_success_rate,
        bug_detection_rate=bug_detection_rate,
        avg_repair_rounds_all=avg_rounds_all,
        avg_repair_rounds_on_repaired=avg_rounds_repaired,
        e2e_latency_p50_ms=p50_lat,
        e2e_latency_p95_ms=p95_lat,
        sandbox_failure_rate=sandbox_failure_rate,
        failure_distribution=failure_dist,
        category_metrics=compute_group_metrics(category_runs),
        difficulty_metrics=compute_group_metrics(difficulty_runs),
        provenance=provenance_meta,
    )
