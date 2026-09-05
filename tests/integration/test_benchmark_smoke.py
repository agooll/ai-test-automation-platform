from pathlib import Path
import pytest

from testteller.benchmark.loader import (
    load_all_cases,
    load_all_projects,
    load_benchmark_suite,
)
from testteller.benchmark.metrics import aggregate_benchmark_runs
from testteller.benchmark.reporter import BenchmarkReporter
from testteller.benchmark.runner import BenchmarkRunner


def test_benchmark_smoke_closed_loop_integration(tmp_path: Path):
    """End-to-end integration test verifying real OSS projects, oracle, metrics, and reporter."""
    root = Path(__file__).resolve().parent.parent.parent
    evals_dir = root / "evals"

    # 1. Load real OSS datasets
    projects = load_all_projects(evals_dir / "projects")
    cases = load_all_cases(evals_dir / "cases", base_dir=root, verify_files_exist=True)
    smoke_suite = load_benchmark_suite(evals_dir / "suites" / "smoke_v1.yaml")

    # 2. Agent workflow that writes targeted test files exercising the entrypoints
    class TargetAgentWorkflow:
        def __init__(self, workspace_dir: Path, framework: str):
            self.workspace_dir = workspace_dir
            self.framework = framework

        def run(self, state: dict):
            tests_dir = self.workspace_dir / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            
            entrypoint = state.get("target_entrypoint", "")
            if "LRUCache" in entrypoint or "cachetools" in entrypoint:
                # Tests cachetools.LRUCache
                test_file = tests_dir / "test_lru_cache.py"
                test_code = """import pytest
from cachetools import LRUCache

def test_lru_cache_storage():
    cache = LRUCache(maxsize=2)
    cache['a'] = 1
    cache['b'] = 2
    assert cache['a'] == 1
    assert cache['b'] == 2
    assert cache.currsize == 2
"""
                test_file.write_text(test_code, encoding="utf-8")
                gen_dict = {str(test_file): test_code}
            else:
                # Tests bottle dynamic route
                test_file = tests_dir / "test_bottle_route.py"
                test_code = """import pytest
from bottle import Bottle

def test_bottle_dynamic_route():
    app = Bottle()
    @app.route('/hello/<name>')
    def greet(name):
        return f"Hello {name}!"
    
    res = app._handle({'PATH_INFO': '/hello/Alice', 'REQUEST_METHOD': 'GET'})
    assert res == 'Hello Alice!'
"""
                test_file.write_text(test_code, encoding="utf-8")
                gen_dict = {str(test_file): test_code}

            return {
                "execution_success": True,
                "execution_result": {"passed": True},
                "repair_round": 0,
                "trace": [
                    {"node": "execute", "tools": {"run_tests": {"data": {"passed": True, "duration_ms": 50}}}},
                ],
                "generated_files": gen_dict,
            }

    # 3. Use local execution backend for the integration test runner
    runner = BenchmarkRunner(
        projects=projects,
        cases=cases,
        base_dir=root,
        execution_backend="local",
        workflow_factory=lambda ws, fw: TargetAgentWorkflow(ws, fw),
        allow_fallback=True,
    )

    # 4. Run smoke suite (case_01 on cachetools, case_13 on bottle)
    results = runner.run_suite(smoke_suite, repeats=1)

    assert len(results) == 2
    assert results[0].case_id == "case_01"
    assert results[1].case_id == "case_13"

    for r in results:
        assert r.passed_first is True
        assert r.passed_final is True
        assert r.clean_exec_passed is True
        # Dual-oracle: clean PASS and mutant FAIL (detected)
        assert r.semantic_success is True
        assert len(r.mutant_results) == 1
        assert r.mutant_results[0].detected is True
        # Provenance verification
        assert len(r.provenance["commit_sha"]) == 40
        assert r.provenance["corpus_hash"] != ""

    # 5. Aggregate metrics
    summary = aggregate_benchmark_runs("smoke_v1", cases, results, repeats_per_case=1)
    assert summary.first_pass_rate == 1.0
    assert summary.final_pass_rate == 1.0
    assert summary.semantic_success_rate == 1.0
    assert summary.bug_detection_rate == 1.0
    assert summary.avg_repair_rounds_all == 0.0

    # 6. Generate and verify report artifacts
    reporter = BenchmarkReporter(tmp_path / "reports")
    report_paths = reporter.write_all(summary, results)

    assert report_paths["summary_json"].exists()
    assert report_paths["runs_jsonl"].exists()
    assert report_paths["report_md"].exists()

    md_text = report_paths["report_md"].read_text(encoding="utf-8")
    assert "TestTeller Benchmark Report: smoke_v1" in md_text
    assert "Dual-Oracle Semantic Success" in md_text
    assert "Seeded Bug Detection Rate" in md_text
    assert "100.0%" in md_text
