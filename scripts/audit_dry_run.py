import json
import os
import sys

def audit_dry_run(report_dir):
    runs_file = os.path.join(report_dir, "runs.jsonl")
    summary_file = os.path.join(report_dir, "summary.json")

    with open(summary_file, "r", encoding="utf-8") as f:
        summary = json.load(f)

    print("=== SUMMARY METRICS ===")
    print(f"Suite: {summary.get('suite_id')}")
    print(f"Total Cases: {summary.get('total_cases')}, Total Runs: {summary.get('total_runs')}")
    print(f"First Pass Rate: {summary.get('first_pass_rate'):.1%}")
    print(f"Final Pass Rate: {summary.get('final_pass_rate'):.1%}")
    print(f"Bug Detection Rate: {summary.get('bug_detection_rate'):.1%}")
    print(f"Semantic Success Rate: {summary.get('semantic_success_rate'):.1%}")
    print(f"Avg Repair Rounds: {summary.get('avg_repair_rounds_all'):.2f}")
    print(f"Sandbox Failure Rate: {summary.get('sandbox_failure_rate'):.1%}")
    print(f"Failure Distribution: {summary.get('failure_distribution')}")

    prov = summary.get("provenance", {})
    print("\n=== PROVENANCE METRICS ===")
    print(f"actual_backend: {prov.get('actual_backend')}")
    print(f"actual_runner_image: {prov.get('actual_runner_image')}")
    print(f"actual_runner_digest: {prov.get('actual_runner_digest')}")
    print(f"actual_model_provider: {prov.get('actual_model_provider')}")
    print(f"actual_model_name: {prov.get('actual_model_name')}")
    print(f"fallback_used: {prov.get('fallback_used')}")
    print(f"testteller_commit: {prov.get('testteller_commit')}")
    print(f"target_commits: {prov.get('target_commits')}")

    runs = []
    with open(runs_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                runs.append(json.loads(line))

    print("\n=== CASE-BY-CASE BREAKDOWN (24 Cases) ===")
    mutant_stats = {"total": 0, "detected": 0}
    patch_failures = []
    missing_deps = []
    timeouts = []
    assertion_fails = []
    repair_exhausted = []

    for r in runs:
        cid = r["case_id"]
        p1 = r["passed_first"]
        pf = r["passed_final"]
        sem = r["semantic_success"]
        rep = r["repaired"]
        rounds = r["repair_rounds"]
        ftype = r["failure_type"]
        muts = r.get("mutant_results", [])
        m_det = sum(1 for m in muts if m.get("detected"))
        m_tot = len(muts)
        mutant_stats["total"] += m_tot
        mutant_stats["detected"] += m_det

        if ftype == "missing_dependency":
            missing_deps.append(cid)
        elif ftype == "timeout":
            timeouts.append(cid)
        elif ftype == "assertion_failure":
            assertion_fails.append(cid)
        elif ftype == "repair_exhausted":
            repair_exhausted.append(cid)

        # Check if mutants had patch errors
        for m in muts:
            if "patch" in m.get("output_snippet", "").lower() or m.get("exit_code") == 127:
                patch_failures.append((cid, m))

        print(f"[{cid}] P1:{str(p1):<5} PF:{str(pf):<5} Sem:{str(sem):<5} Rep:{str(rep):<5} Rnd:{rounds} M:{m_det}/{m_tot} Fail:{ftype}")

    print("\n=== AUDIT FINDINGS ===")
    print(f"Total Mutants Evaluated: {mutant_stats['total']}, Detected: {mutant_stats['detected']}")
    print(f"Patch Apply Failures: {len(patch_failures)}")
    if patch_failures:
        for p in patch_failures:
            print(f"  Patch error on {p[0]}: {p[1]}")
    print(f"Missing Dependencies: {missing_deps}")
    print(f"Timeouts: {timeouts}")
    print(f"Repair Exhausted: {repair_exhausted}")
    print(f"Assertion Failures: {assertion_fails}")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "evals/reports/dry_run_9975671318/benchmark_v1_20260905_191405"
    audit_dry_run(path)
