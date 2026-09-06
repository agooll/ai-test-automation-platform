#!/usr/bin/env python3
"""Runner for Stage 4 Quality Gate & Anti-Fake Certification."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from testteller.quality_gate.anti_fake_metrics import run_full_anti_fake_evaluation


def format_markdown_report(summary) -> str:
    vac_verdict = "PASS" if summary.vacuous_test_detection_rate >= 0.95 else "FAIL"
    hal_verdict = "PASS" if summary.hallucination_detection_rate >= 0.95 else "FAIL"
    weak_verdict = "PASS" if summary.repair_weakening_rate >= 0.95 else "FAIL"
    fr_verdict = "PASS" if summary.false_rejection_rate <= 0.05 else "FAIL"
    ground_verdict = "PASS" if summary.grounded_claim_rate >= 0.90 else "FAIL"
    qual_verdict = "PASS" if summary.quality_adjusted_pass_rate >= 0.95 else "FAIL"

    overall_pass = (
        vac_verdict == "PASS"
        and hal_verdict == "PASS"
        and weak_verdict == "PASS"
        and fr_verdict == "PASS"
        and ground_verdict == "PASS"
        and qual_verdict == "PASS"
    )
    overall_verdict = "ACCEPTED" if overall_pass else "NOT ACCEPTED"

    md = f"""# TestTeller Stage 4 Quality Gate & Anti-Fake Certification Report

## 1. Executive Summary

- **Certification Status**: **{overall_verdict}**
- **Git Commit Provenance**: `{summary.git_commit or 'unknown'}`
- **Suite Hash (SHA-256)**: `{summary.suite_hash or 'unknown'}`
- **Timestamp (UTC)**: `{summary.evaluated_at or 'unknown'}`

This report evaluates the **Stage 4 Quality Gate and Anti-Fake Certification** across 4 dedicated quality suites:
1. **Vacuous Tests**: Empty bodies, tautological assertions, swallowed exceptions, unconditional skips, unrelated stdlib helpers.
2. **Hallucinations**: Fabricated SUT methods, non-existent classes, unsupported API endpoints, unsupported UI selectors.
3. **Repair Weakening**: Assertion deletion, equality softened to `is not None` / truthiness, exception broadening, added mocks, added skips, loosened bounds.
4. **Legitimate Tests**: Genuine, grounded, robust tests verifying real SUT invariants.

---

## 2. Core Anti-Fake Metrics

| Metric | Measured Value | Benchmark Target | Verdict |
| :--- | :---: | :---: | :---: |
| **Vacuous Test Detection Rate** | **{summary.vacuous_test_detection_rate * 100:.1f}%** ({summary.vacuous_detected}/{summary.total_vacuous_cases}) | $\\ge 95.0\\%$ | {vac_verdict} |
| **Hallucination Detection Rate** | **{summary.hallucination_detection_rate * 100:.1f}%** ({summary.hallucinations_detected}/{summary.total_hallucination_cases}) | $\\ge 95.0\\%$ | {hal_verdict} |
| **Repair Weakening Detection Rate** | **{summary.repair_weakening_rate * 100:.1f}%** ({summary.weakening_detected}/{summary.total_weakening_cases}) | $\\ge 95.0\\%$ | {weak_verdict} |
| **False Rejection Rate (Legitimate)** | **{summary.false_rejection_rate * 100:.1f}%** ({summary.total_legitimate_cases - summary.legitimate_passed}/{summary.total_legitimate_cases}) | $\\le 5.0\\%$ | {fr_verdict} |
| **Grounded Claim Rate** | **{summary.grounded_claim_rate * 100:.1f}%** ({summary.grounded_claims}/{summary.total_claims}) | $\\ge 90.0\\%$ | {ground_verdict} |
| **Quality-Adjusted Pass Rate** | **{summary.quality_adjusted_pass_rate * 100:.1f}%** | $\\ge 95.0\\%$ | {qual_verdict} |


---

## 3. Case Breakdown

### Vacuous Test Detection
"""
    for r in summary.details.get("vacuous", []):
        md += f"- `{r['case']}`: Status = **{r['status']}**, Detected = **{r['detected']}**, Violations = `{r['violations']}`\n"

    md += "\n### Hallucination Detection\n"
    for r in summary.details.get("hallucination", []):
        md += f"- `{r['case']}`: Status = **{r['status']}**, Detected = **{r['detected']}**\n"

    md += "\n### Repair Weakening Detection\n"
    for r in summary.details.get("repair_weakening", []):
        md += f"- `{r['id']}` ({r['pattern']}): Weakened = **{r['is_weakened']}** (Expected: **{r['expected_weakened']}**) -> Correct = **{r['correct']}**\n"

    md += "\n### Legitimate Test Verification\n"
    for r in summary.details.get("legitimate", []):
        md += f"- `{r['case']}`: Status = **{r['status']}**, Allow Final Pass = **{r['allow_final_pass']}**\n"

    return md


async def main():
    parser = argparse.ArgumentParser(description="Run Stage 4 Anti-Fake Evaluation Benchmark")
    parser.add_argument("--evals-dir", type=str, default=str(REPO_ROOT / "evals" / "quality"), help="Path to evals/quality")
    parser.add_argument("--output-json", type=str, default=str(REPO_ROOT / "evals" / "reports" / "quality_eval_summary.json"), help="Output JSON path")
    parser.add_argument("--output-md", type=str, default=str(REPO_ROOT / "evals" / "reports" / "quality_eval_report.md"), help="Output Markdown report path")
    args = parser.parse_args()

    print(f"=== Running Stage 4 Anti-Fake Benchmark on {args.evals_dir} ===")
    summary = await run_full_anti_fake_evaluation(Path(args.evals_dir))

    # Print terminal table
    print("\n" + "=" * 60)
    print("STAGE 4 QUALITY GATE & ANTI-FAKE CERTIFICATION RESULTS")
    print("=" * 60)
    print(f"Vacuous Test Detection Rate:      {summary.vacuous_test_detection_rate * 100:6.2f}% ({summary.vacuous_detected}/{summary.total_vacuous_cases})")
    print(f"Hallucination Detection Rate:     {summary.hallucination_detection_rate * 100:6.2f}% ({summary.hallucinations_detected}/{summary.total_hallucination_cases})")
    print(f"Repair Weakening Detection Rate:  {summary.repair_weakening_rate * 100:6.2f}% ({summary.weakening_detected}/{summary.total_weakening_cases})")
    print(f"False Rejection Rate:             {summary.false_rejection_rate * 100:6.2f}% ({summary.total_legitimate_cases - summary.legitimate_passed}/{summary.total_legitimate_cases})")
    print(f"Grounded Claim Rate:              {summary.grounded_claim_rate * 100:6.2f}%")
    print(f"Quality-Adjusted Pass Rate:       {summary.quality_adjusted_pass_rate * 100:6.2f}%")
    print("=" * 60 + "\n")

    # Write output reports
    json_path = Path(args.output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary.model_dump(mode="json"), indent=2), encoding="utf-8")
    print(f"JSON summary written to: {json_path}")

    md_report = format_markdown_report(summary)
    md_path = Path(args.output_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_report, encoding="utf-8")
    print(f"Markdown report written to: {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
