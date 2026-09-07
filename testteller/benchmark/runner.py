"""Benchmark Suite Runner for executing and evaluating benchmark cases."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Sequence

from testteller.agent_runtime.adapters import build_existing_rag_workflow
from testteller.agent_runtime.evaluation import classify_failure
from testteller.automator_agent.parser.markdown_parser import (
    MarkdownTestCaseParser,
    TestCase,
    TestStep,
)
from testteller.automator_agent.rag_enhanced_generator import RAGEnhancedTestGenerator
from testteller.benchmark.oracle import DualOracleEvaluator
from testteller.benchmark.project import BenchmarkProjectManager
from testteller.benchmark.schema import (
    BenchmarkCase,
    BenchmarkRunResult,
    BenchmarkSuite,
    ProjectManifest,
)
from testteller.core.llm.llm_manager import LLMManager, OfflineFallbackLLMClient
from testteller.core.vector_store.chromadb_manager import ChromaDBManager

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Orchestrates end-to-end evaluation of benchmark suites against TestTeller Automation Agent."""

    def __init__(
        self,
        projects: dict[str, ProjectManifest],
        cases: dict[str, BenchmarkCase],
        base_dir: Path | None = None,
        execution_backend: str = "docker",
        model_name: str = "gemini-2.5-pro",
        allow_fallback: bool = False,
        llm_manager: LLMManager | None = None,
        chroma_persist_dir: Path | None = None,
        project_manager: BenchmarkProjectManager | None = None,
        oracle_evaluator: DualOracleEvaluator | None = None,
        workflow_factory: Callable[..., Any] | None = None,
    ):
        self.base_dir = (base_dir or Path.cwd()).resolve()
        self.projects = projects
        self.cases = cases
        self.execution_backend = execution_backend
        self.model_name = model_name
        self.allow_fallback = allow_fallback
        self._llm_manager = llm_manager
        self.chroma_persist_dir = chroma_persist_dir or (self.base_dir / "chroma_data")
        self.project_manager = project_manager or BenchmarkProjectManager(self.base_dir)
        self.oracle_evaluator = oracle_evaluator or DualOracleEvaluator(execution_backend=self.execution_backend)
        self.workflow_factory = workflow_factory

    @property
    def llm_manager(self) -> LLMManager:
        if self._llm_manager is None:
            self._llm_manager = LLMManager(generation_model=self.model_name, allow_fallback=self.allow_fallback)
        return self._llm_manager

    def _build_production_workflow(
        self,
        manifest: ProjectManifest,
        work_dir: Path,
        test_cases: list[TestCase],
    ) -> tuple[Any, str]:
        """Construct the real production TestTeller Automation Agent workflow with frozen RAG snapshot."""
        import os
        os.environ["ENABLE_TEST_CASE_FEEDBACK"] = "false"

        collection_name, corpus_hash = self.project_manager.build_or_load_static_rag_snapshot(
            manifest, self.chroma_persist_dir, self.llm_manager
        )

        vector_store = ChromaDBManager(
            llm_manager=self.llm_manager,
            collection_name=collection_name,
            persist_directory=str(self.chroma_persist_dir),
        )

        generator = RAGEnhancedTestGenerator(
            framework=manifest.test_framework,
            output_dir=work_dir,
            vector_store=vector_store,
            language=manifest.language,
            llm_manager=self.llm_manager,
        )

        workflow = build_existing_rag_workflow(
            generator=generator,
            test_cases=test_cases,
            llm_manager=self.llm_manager,
            checkpoint_path=None,
            execution_backend=self.execution_backend,
        )
        return workflow, corpus_hash

    def run_case(self, case: BenchmarkCase, run_index: int = 1) -> BenchmarkRunResult:
        """Run a single evaluation iteration for a given benchmark case."""
        manifest = self.projects.get(case.project_name)
        if not manifest:
            raise KeyError(f"Project manifest '{case.project_name}' not found for case '{case.case_id}'")

        # Read requirement text
        req_path = Path(case.requirement_path)
        if not req_path.is_absolute():
            req_path = (self.base_dir / req_path).resolve()
        if not req_path.exists():
            raise FileNotFoundError(f"Requirement file not found: {req_path}")
        requirement_text = req_path.read_text(encoding="utf-8")

        # Parse or construct structured TestCase
        parsed_cases = MarkdownTestCaseParser().parse_content(requirement_text)
        if not parsed_cases:
            first_line = requirement_text.strip().splitlines()[0].lstrip("#").strip() if requirement_text.strip() else case.case_id
            test_cases = [
                TestCase(
                    id=case.case_id,
                    feature=case.project_name,
                    type="automated",
                    category=case.category,
                    objective=first_line,
                    test_steps=[
                        TestStep(
                            action=f"Test entrypoint {case.target_entrypoint}",
                            technical_details=requirement_text,
                        )
                    ],
                )
            ]
        else:
            test_cases = parsed_cases

        # Measure full outer E2E pipeline duration
        t0 = time.perf_counter()

        with tempfile.TemporaryDirectory(prefix=f"bench_{case.case_id}_run{run_index}_") as temp_dir:
            work_dir = Path(temp_dir) / "workspace"
            self.project_manager.create_isolated_workspace(manifest, work_dir)

            try:
                # Build production workflow or use injected factory
                if self.workflow_factory:
                    workflow = self.workflow_factory(work_dir, manifest.test_framework)
                    corpus_hash = self.project_manager.compute_corpus_hash(manifest)
                else:
                    workflow, corpus_hash = self._build_production_workflow(manifest, work_dir, test_cases)

                test_cmd = ["pytest", "-v", "tests"] if manifest.test_framework == "pytest" else ["npm", "test"]

                target_repo_path = str(self.project_manager.resolve_project_source(manifest))

                state: dict[str, Any] = {
                    "task_id": f"{case.case_id}_run{run_index}",
                    "workspace": str(work_dir),
                    "workspace_dir": str(work_dir),
                    "target_repo": target_repo_path,
                    "repo_path": target_repo_path,
                    "pinned_commit": manifest.commit_sha,
                    "language": manifest.language,
                    "framework": manifest.test_framework,
                    "test_framework": manifest.test_framework,
                    "test_command": test_cmd,
                    "requirement": requirement_text,
                    "target_entrypoint": case.target_entrypoint,
                    "max_repair_rounds": 2,
                    "execution_backend": self.execution_backend,
                }

                # Run the agent workflow
                if asyncio.iscoroutinefunction(getattr(workflow, "run", None)):
                    agent_result = asyncio.run(workflow.run(state))
                else:
                    agent_result = workflow.run(state)
            except Exception as e:
                logger.exception("Agent workflow execution failed for %s run %d: %s", case.case_id, run_index, e)
                agent_result = {
                    "execution_success": False,
                    "execution_result": {"passed": False, "stderr": str(e)},
                    "trace": [],
                    "repair_round": 0,
                }
                corpus_hash = self.project_manager.compute_corpus_hash(manifest)

            t1 = time.perf_counter()
            e2e_duration_ms = (t1 - t0) * 1000.0

            # Analyze execution trace
            trace = agent_result.get("trace", [])
            executions = [
                ev.get("tools", {}).get("run_tests", {}).get("data", {})
                for ev in trace if ev.get("node") == "execute"
            ]

            passed_first = bool(executions and executions[0].get("passed", False))
            passed_final = bool(
                agent_result.get("execution_success", agent_result.get("execution_result", {}).get("passed", False))
            )
            repaired = bool(passed_final and not passed_first)
            repair_rounds = int(agent_result.get("repair_round", 0))

            failure_type = classify_failure(agent_result)

            # Discover all test files generated in this run
            gen_files = list(agent_result.get("generated_files", {}).keys())
            if not gen_files and (work_dir / "tests").exists():
                gen_files = [str(p.relative_to(work_dir)) for p in (work_dir / "tests").rglob("*.py")]
            elif not gen_files:
                gen_files = [
                    str(p.relative_to(work_dir))
                    for p in work_dir.glob("test_*.py")
                    if ".pytest_cache" not in str(p)
                ]

            # Perform Dual-Oracle Semantic Evaluation strictly on generated test files
            try:
                clean_passed, mutant_results, semantic_success = self.oracle_evaluator.evaluate(
                    clean_workspace_dir=work_dir,
                    test_framework=manifest.test_framework,
                    mutants=case.mutants,
                    base_dir=self.base_dir,
                    generated_test_files=gen_files,
                    timeout_sec=case.timeout_sec,
                )
            except Exception as e:
                logger.warning("Dual oracle evaluation encountered error for %s: %s", case.case_id, e)
                clean_passed = False
                mutant_results = []
                semantic_success = False

            # Harvest actual runtime provenance
            executions = agent_result.get("execution_history", [])
            last_exec = executions[-1] if executions else agent_result.get("execution_result", {})
            actual_backend = last_exec.get("backend", self.execution_backend)

            # Local execution strictly has NO Docker image or digest
            if str(actual_backend).lower() == "local":
                actual_runner_image = None
                actual_runner_digest = None
            else:
                actual_runner_image = last_exec.get("runner_image")
                actual_runner_digest = last_exec.get("runner_digest")

            fallback_used = isinstance(getattr(self.llm_manager, "client", None), OfflineFallbackLLMClient)
            if fallback_used:
                # Do NOT write Gemini as actual model when offline fallback was used
                actual_model_provider = "offline"
                actual_model_name = "offline-fallback"
            else:
                actual_model_provider = getattr(self.llm_manager, "provider", "unknown")
                actual_model_name = getattr(self.llm_manager, "generation_model", self.model_name)

            provenance = self.project_manager.get_provenance_metadata(
                manifest,
                model_name=actual_model_name,
                corpus_hash=corpus_hash,
                actual_backend=actual_backend,
                actual_runner_image=actual_runner_image,
                actual_runner_digest=actual_runner_digest,
                actual_model_provider=actual_model_provider,
                actual_model_name=actual_model_name,
                fallback_used=fallback_used,
            )

            return BenchmarkRunResult(
                case_id=case.case_id,
                run_index=run_index,
                passed_first=passed_first,
                passed_final=passed_final,
                repaired=repaired,
                repair_rounds=repair_rounds,
                e2e_duration_ms=e2e_duration_ms,
                clean_exec_passed=clean_passed,
                mutant_results=mutant_results,
                semantic_success=semantic_success,
                failure_type=failure_type,
                provenance=provenance,
                trace=trace,
                generated_files=gen_files,
            )

    def run_suite(
        self,
        suite: BenchmarkSuite,
        repeats: int | None = None,
        on_run_complete: Callable[[BenchmarkRunResult], None] | None = None,
    ) -> list[BenchmarkRunResult]:
        """Execute a full benchmark suite across all cases and repetitions."""
        # Enforce Docker and forbid fallback for formal benchmark suites
        is_smoke = "smoke" in suite.suite_id.lower()
        if not is_smoke:
            if self.execution_backend.lower() != "docker":
                raise ValueError(
                    f"Formal benchmark suite '{suite.suite_id}' strictly requires execution_backend='docker'. "
                    "Local execution is only permitted for smoke testing (e.g. smoke_v1)."
                )
            if self.allow_fallback:
                raise ValueError(
                    f"Formal benchmark suite '{suite.suite_id}' strictly forbids allow_fallback=True. "
                    "Fallback to offline mock LLM is prohibited in formal evaluations."
                )

        num_repeats = repeats if repeats is not None else suite.default_repeats
        all_results: list[BenchmarkRunResult] = []

        for cid in suite.cases:
            case = self.cases.get(cid)
            if not case:
                raise KeyError(f"Case '{cid}' referenced in suite '{suite.suite_id}' not found.")

            for r_idx in range(1, num_repeats + 1):
                logger.info("Executing case %s [run %d/%d]...", cid, r_idx, num_repeats)
                res = self.run_case(case, run_index=r_idx)
                all_results.append(res)
                if on_run_complete:
                    on_run_complete(res)

        return all_results
