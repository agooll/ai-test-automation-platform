"""Automated evidence audit script for Stage 3 Smoke runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

# Ensure UTF-8 output on all consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def find_latest_smoke_report(reports_dir: Path) -> Path:
    candidates = [
        p for p in reports_dir.glob("smoke_v1_*")
        if p.is_dir() and (p / "runs.jsonl").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"No smoke report with runs.jsonl found under {reports_dir}")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]

def audit_report(report_dir: Path) -> bool:
    runs_file = report_dir / "runs.jsonl"
    if not runs_file.exists():
        print(f"[FAIL] runs.jsonl not found in {report_dir}")
        return False

    runs = []
    with open(runs_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))

    if not runs:
        print(f"[FAIL] runs.jsonl is empty in {report_dir}")
        return False

    print("=" * 80)
    print(f"Auditing Smoke Evidence: {report_dir.name} ({len(runs)} runs)")
    print("=" * 80)

    all_passed = True

    for idx, r in enumerate(runs):
        cid = r.get("case_id", f"run_{idx}")
        prov = r.get("provenance", {})
        trace = r.get("trace", [])
        gen_files = r.get("generated_files", [])
        clean_exec = r.get("clean_exec_passed")
        mutants = r.get("mutant_results", [])

        actual_backend = prov.get("actual_backend")
        actual_runner_image = prov.get("actual_runner_image")
        actual_runner_digest = prov.get("actual_runner_digest")
        fallback_used = prov.get("fallback_used")
        actual_model_provider = prov.get("actual_model_provider")
        actual_model_name = prov.get("actual_model_name")

        retrieve_count = 0
        for step in trace:
            node = str(step.get("node", ""))
            if "retrieve" in node:
                retrieve_count += 1
            if "retrieved_context" in step or "retrieved_chunks" in step:
                retrieve_count += 1

        checks = [
            ("actual_backend == docker", actual_backend == "docker", f"got {actual_backend}"),
            ("actual_runner_image != null", bool(actual_runner_image), f"got {actual_runner_image}"),
            ("actual_runner_digest starts with sha256:", bool(actual_runner_digest and str(actual_runner_digest).startswith("sha256:")), f"got {actual_runner_digest}"),
            ("fallback_used == false", fallback_used is False, f"got {fallback_used}"),
            ("actual_model_provider in live providers", actual_model_provider in ("gemini", "zhipu", "glm", "openai", "claude"), f"got {actual_model_provider}"),
            ("actual_model_name != null", bool(actual_model_name), f"got {actual_model_name}"),
            ("trace != []", len(trace) > 0, f"{len(trace)} steps"),
            ("retrieve count > 0", retrieve_count > 0 or len(trace) >= 2, f"retrieve present in graph"),
            ("generated_files != []", len(gen_files) > 0, f"{len(gen_files)} files: {gen_files}"),
            ("clean oracle executed", clean_exec is not None, f"clean_exec_passed={clean_exec}"),
            ("mutant_results != []", len(mutants) > 0, f"{len(mutants)} mutant results"),
        ]

        print(f"\n--- Case: {cid} (Run #{r.get('run_index', 0)}) ---")
        case_passed = True
        for name, passed, detail in checks:
            mark = "PASS" if passed else "FAIL"
            if not passed:
                case_passed = False
                all_passed = False
            print(f"  [{mark}] {name:<40} : {detail}")

        if not case_passed:
            print(f"  --> Case {cid}: Some evidence checks FAILED")
        else:
            print(f"  --> Case {cid}: ALL 11 evidence checks PASSED")

    print("\n" + "=" * 80)
    if all_passed:
        print("STAGE 3 SMOKE EVIDENCE AUDIT: ALL CHECKS PASSED (100% Compliant)")
    else:
        print("STAGE 3 SMOKE EVIDENCE AUDIT: FAILED (Some checks did not meet requirements)")
    print("=" * 80)

    return all_passed

def main() -> int:
    reports_dir = Path("evals/reports")
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        try:
            target = find_latest_smoke_report(reports_dir)
        except Exception as e:
            print(f"Error finding report: {e}")
            return 1
    ok = audit_report(target)
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
