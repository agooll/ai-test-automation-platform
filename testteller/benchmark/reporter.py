"""Multi-format report generation (JSON, JSONL, Markdown) for Benchmark results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from testteller.benchmark.schema import BenchmarkRunResult, BenchmarkSummary


class BenchmarkReporter:
    """Generates comprehensive summary.json, runs.jsonl, and report.md artifacts."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_summary_json(self, summary: BenchmarkSummary) -> Path:
        summary_path = self.output_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.as_dict(), f, indent=2, ensure_ascii=False)
        return summary_path

    def write_runs_jsonl(self, runs: Sequence[BenchmarkRunResult]) -> Path:
        runs_path = self.output_dir / "runs.jsonl"
        with open(runs_path, "w", encoding="utf-8") as f:
            for r in runs:
                f.write(json.dumps(r.as_dict(), ensure_ascii=False) + "\n")
        return runs_path

    def write_markdown_report(self, summary: BenchmarkSummary) -> Path:
        md_path = self.output_dir / "report.md"

        cat_rows = []
        for cat, m in sorted(summary.category_metrics.items()):
            cat_rows.append(
                f"| `{cat}` | {m['total_runs']} | {m['first_pass_rate']*100:.1f}% | {m['final_pass_rate']*100:.1f}% | {m['semantic_success_rate']*100:.1f}% |"
            )

        diff_rows = []
        for diff, m in sorted(summary.difficulty_metrics.items()):
            diff_rows.append(
                f"| `{diff}` | {m['total_runs']} | {m['first_pass_rate']*100:.1f}% | {m['final_pass_rate']*100:.1f}% | {m['semantic_success_rate']*100:.1f}% |"
            )

        fail_rows = []
        for ftype, cnt in sorted(summary.failure_distribution.items()):
            fail_rows.append(f"| `{ftype}` | {cnt} |")
        if not fail_rows:
            fail_rows.append("| *None (All passed)* | 0 |")

        prov_items = []
        for k, v in sorted(summary.provenance.items()):
            prov_items.append(f"- **{k}**: `{v}`")

        content = f"""# TestTeller Benchmark Report: {summary.suite_id}

## 1. Executive Summary

| Evaluation Dimension | Value |
| :--- | :--- |
| **Total Cases** | {summary.total_cases} |
| **Total Runs** | {summary.total_runs} (Repeats per case: {summary.repeats_per_case}) |
| **First Execution Pass Rate** | **{summary.first_pass_rate*100:.1f}%** |
| **Final Execution Pass Rate** | **{summary.final_pass_rate*100:.1f}%** |
| **Repair Recovery Rate** | **{summary.repair_recovery_rate*100:.1f}%** |
| **Repair Uplift** | **+{summary.repair_uplift*100:.1f}% pts** |
| **Dual-Oracle Semantic Success** | **{summary.semantic_success_rate*100:.1f}%** |
| **Seeded Bug Detection Rate** | **{summary.bug_detection_rate*100:.1f}%** |
| **Average Repair Rounds (All)** | {summary.avg_repair_rounds_all:.2f} |
| **Average Repair Rounds (Repaired)** | {summary.avg_repair_rounds_on_repaired:.2f} |
| **E2E Latency (p50)** | {summary.e2e_latency_p50_ms:.1f} ms |
| **E2E Latency (p95)** | {summary.e2e_latency_p95_ms:.1f} ms |
| **Sandbox Environment Failure Rate** | {summary.sandbox_failure_rate*100:.1f}% |

---

## 2. Category Performance Breakdown

| Category | Runs | First Pass | Final Pass | Semantic Success |
| :--- | :--- | :--- | :--- | :--- |
{chr(10).join(cat_rows)}

---

## 3. Difficulty Level Breakdown

| Difficulty | Runs | First Pass | Final Pass | Semantic Success |
| :--- | :--- | :--- | :--- | :--- |
{chr(10).join(diff_rows)}

---

## 4. Failure Taxonomy Distribution

| Failure Classification | Count |
| :--- | :--- |
{chr(10).join(fail_rows)}

---

## 5. Reproducibility & Provenance Metadata

{chr(10).join(prov_items)}
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)
        return md_path

    def write_all(self, summary: BenchmarkSummary, runs: Sequence[BenchmarkRunResult]) -> dict[str, Path]:
        """Write summary.json, runs.jsonl, and report.md."""
        return {
            "summary_json": self.write_summary_json(summary),
            "runs_jsonl": self.write_runs_jsonl(runs),
            "report_md": self.write_markdown_report(summary),
        }
