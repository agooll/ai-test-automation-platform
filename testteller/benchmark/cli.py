"""CLI command implementation for running the TestTeller Benchmark Suite."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import sys

from testteller.benchmark.loader import (
    load_all_cases,
    load_all_projects,
    load_benchmark_suite,
)
from testteller.benchmark.metrics import aggregate_benchmark_runs
from testteller.benchmark.reporter import BenchmarkReporter
from testteller.benchmark.runner import BenchmarkRunner

logger = logging.getLogger(__name__)


def benchmark_command(
    suite: str = "evals/suites/smoke_v1.yaml",
    repeats: int | None = None,
    backend: str = "docker",
    output_dir: str | None = None,
    model: str = "gemini-2.5-pro",
    allow_fallback: bool = False,
) -> int:
    """Entry point for `testteller benchmark` CLI command."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    root_dir = Path.cwd().resolve()
    evals_dir = root_dir / "evals"

    # 1. Resolve suite path
    suite_path = Path(suite)
    if not suite_path.is_absolute():
        if (root_dir / suite_path).exists():
            suite_path = root_dir / suite_path
        elif (evals_dir / "suites" / f"{suite}.yaml").exists():
            suite_path = evals_dir / "suites" / f"{suite}.yaml"
        elif (evals_dir / "suites" / suite).exists():
            suite_path = evals_dir / "suites" / suite
        else:
            suite_path = (root_dir / suite_path).resolve()

    if not suite_path.exists():
        print(f"❌ Benchmark suite not found: {suite_path}")
        return 1

    print(f"📦 Loading benchmark configuration from: {suite_path}...")
    suite_def = load_benchmark_suite(suite_path)

    # Formal benchmark suite strictly requires Docker and forbids --allow-fallback
    is_smoke = "smoke" in suite_def.suite_id.lower() or "smoke" in suite_path.name.lower()
    if not is_smoke:
        if backend.lower() != "docker":
            print(
                f"❌ Formal benchmark suite '{suite_def.suite_id}' strictly requires --backend docker. "
                "Local execution is only allowed for smoke testing (e.g. smoke_v1)."
            )
            return 1
        if allow_fallback:
            print(
                f"❌ Formal benchmark suite '{suite_def.suite_id}' strictly forbids --allow-fallback. "
                "Fallback to offline mock LLM is prohibited in formal evaluations."
            )
            return 1

    projects = load_all_projects(evals_dir / "projects")
    cases = load_all_cases(evals_dir / "cases", base_dir=root_dir, verify_files_exist=True)

    effective_repeats = repeats if repeats is not None else suite_def.default_repeats
    print(f"🚀 Running Benchmark Suite '{suite_def.suite_id}': {len(suite_def.cases)} cases, {effective_repeats} repeat(s) each.")
    print(f"⚙️ Execution Backend: '{backend}' | Model: '{model}' | Allow Fallback: {allow_fallback}")

    # 2. Output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_dir:
        report_dir = Path(output_dir).resolve()
    else:
        report_dir = evals_dir / "reports" / f"{suite_def.suite_id}_{timestamp}"
    report_dir.mkdir(parents=True, exist_ok=True)

    # 3. Initialize Runner
    runner = BenchmarkRunner(
        projects=projects,
        cases=cases,
        base_dir=root_dir,
        execution_backend=backend,
        model_name=model,
        allow_fallback=allow_fallback,
    )

    # 4. Run Suite
    def progress_callback(res):
        status = "✅ PASS" if res.passed_final else "❌ FAIL"
        sem_status = "🎯 DETECTED" if res.semantic_success else "⚠️ WEAK"
        rep_note = f" (repaired in {res.repair_rounds} rounds)" if res.repaired else ""
        print(f"  [{res.case_id} run {res.run_index}] {status}{rep_note} | Dual-Oracle: {sem_status} ({res.e2e_duration_ms:.0f}ms)")

    runs = runner.run_suite(suite_def, repeats=effective_repeats, on_run_complete=progress_callback)

    # 5. Aggregate Metrics
    summary = aggregate_benchmark_runs(
        suite_id=suite_def.suite_id,
        cases=cases,
        runs=runs,
        repeats_per_case=effective_repeats,
    )

    # 6. Generate Reports
    reporter = BenchmarkReporter(report_dir)
    paths = reporter.write_all(summary, runs)

    # 7. Print Terminal Summary Table
    print("\n" + "=" * 65)
    print(f"           TESTTELLER BENCHMARK REPORT: {summary.suite_id}")
    print("=" * 65)
    print(f"  Total Cases:                    {summary.total_cases}")
    print(f"  Total Runs:                     {summary.total_runs} ({summary.repeats_per_case} per case)")
    print(f"  First Execution Pass Rate:      {summary.first_pass_rate*100:.1f}%")
    print(f"  Final Execution Pass Rate:      {summary.final_pass_rate*100:.1f}%")
    print(f"  Repair Recovery Rate:           {summary.repair_recovery_rate*100:.1f}%")
    print(f"  Repair Uplift:                  +{summary.repair_uplift*100:.1f}% pts")
    print(f"  Dual-Oracle Semantic Success:   {summary.semantic_success_rate*100:.1f}%")
    print(f"  Seeded Bug Detection Rate:      {summary.bug_detection_rate*100:.1f}%")
    print(f"  Average Repair Rounds (All):    {summary.avg_repair_rounds_all:.2f}")
    print(f"  Average Repair Rounds (Fixed):  {summary.avg_repair_rounds_on_repaired:.2f}")
    print(f"  E2E Latency p50 / p95:          {summary.e2e_latency_p50_ms:.0f} ms / {summary.e2e_latency_p95_ms:.0f} ms")
    print(f"  Sandbox Failure Rate:           {summary.sandbox_failure_rate*100:.1f}%")
    print("=" * 65)
    print(f"📄 Full Markdown Report:  {paths['report_md']}")
    print(f"📊 Summary JSON:          {paths['summary_json']}")
    print(f"📋 Line Execution Log:    {paths['runs_jsonl']}")
    print("=" * 65 + "\n")

    return 0
