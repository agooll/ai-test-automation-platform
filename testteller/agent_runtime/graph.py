"""LangGraph orchestration for a bounded test generation and repair loop with code quality gates."""

from __future__ import annotations

import asyncio
import difflib
import inspect
import logging
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .state import AgentState
from .checkpoint import AsyncCheckpointStore, CheckpointStore
from pathlib import Path
from .tools import AgentToolRegistry, SafeTestExecutor, SandboxPolicy, WorkspaceArtifacts, create_test_executor
from .trace import TraceRecorder
from .grounding_nodes import (
    grounding_plan_node,
    evidence_build_node,
    claim_bind_node,
    repair_grounding_node,
)
from ..quality_gate.code_gate import AutomationCodeQualityGate
from ..quality_gate.code_models import CodeQualityGateResult
from ..quality_gate.claim_binding import ClaimEvidenceBinding
from ..core.evidence.catalog import EvidenceCatalog2
from ..core.evidence.catalog_builder import EvidenceCatalogBuilder
from ..core.evidence.models import EvidenceRecord, SourceChunk, SourceManifest
from ..core.evidence.repository import EvidenceRepository
from ..automator_agent.repair_planner import RepairChange, RepairGroundingPlanner, RepairPlan

logger = logging.getLogger(__name__)

Planner = Callable[[AgentState], dict[str, Any] | Awaitable[dict[str, Any]]]
Generator = Callable[[AgentState], dict[str, str] | Awaitable[dict[str, str]]]
Retriever = Callable[[AgentState], list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]]
Repairer = Callable[[AgentState], dict[str, str] | Awaitable[dict[str, str]]]
Reviewer = Callable[[AgentState], dict[str, Any] | Awaitable[dict[str, Any]]]
EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


async def _maybe_call(callback: Callable[[AgentState], Any], state: AgentState) -> Any:
    value = callback(state)
    return await value if inspect.isawaitable(value) else value


class AgenticTestWorkflow:
    """A small, inspectable graph instead of an unbounded autonomous loop."""

    def __init__(
        self,
        planner: Planner | None = None,
        retriever: Retriever | None = None,
        generator: Generator | None = None,
        repairer: Repairer | None = None,
        reviewer: Reviewer | None = None,
        code_quality_gate: AutomationCodeQualityGate | None = None,
        tool_registry: AgentToolRegistry | None = None,
        checkpointer: Any | None = None,
        checkpoint_path: str | None = None,
        event_sink: EventSink | None = None,
        execution_backend: str = "auto",
        sandbox_policy: SandboxPolicy | None = None,
    ) -> None:
        self.planner = planner or self._default_planner
        self.retriever = retriever or self._default_retriever
        self.generator = generator or self._default_generator
        self.repairer = repairer or self._default_repairer
        self.reviewer = reviewer or self._default_reviewer
        self.code_quality_gate = code_quality_gate or AutomationCodeQualityGate()
        self.tools = tool_registry or AgentToolRegistry()
        self.event_sink = event_sink
        self.execution_backend = execution_backend
        self.sandbox_policy = sandbox_policy
        self._register_tools()

        self._checkpoint_store = None
        self._async_checkpoint_store = None
        self._checkpoint_path = checkpoint_path
        if checkpointer is None and checkpoint_path:
            checkpointer = MemorySaver()
        self.graph = self._build_graph(checkpointer or MemorySaver())

    def close(self) -> None:
        if self._checkpoint_store:
            self._checkpoint_store.close()
            self._checkpoint_store = None

    async def aclose(self) -> None:
        self.close()
        if self._async_checkpoint_store:
            await self._async_checkpoint_store.close()
            self._async_checkpoint_store = None

    async def _ensure_async_checkpoint(self) -> None:
        if not self._checkpoint_path or self._async_checkpoint_store:
            return
        self._async_checkpoint_store = AsyncCheckpointStore(self._checkpoint_path)
        checkpointer = await self._async_checkpoint_store.start()
        self.graph = self._build_graph(checkpointer)

    def _register_tools(self) -> None:
        if "write_files" not in self.tools.names():
            self.tools.register("write_files", self._write_files)
        if "run_tests" not in self.tools.names():
            self.tools.register("run_tests", self._run_tests)

    async def run(self, state: AgentState, thread_id: str | None = None) -> AgentState:
        await self._ensure_async_checkpoint()
        initial = dict(state)
        initial.setdefault("task_id", str(uuid.uuid4()))
        initial.setdefault("repair_round", 0)
        initial.setdefault("max_repair_rounds", 2)
        initial.setdefault("repair_history", [])
        initial.setdefault("trace", [])
        initial.setdefault("generated_files", {})
        initial.setdefault("code_quality_history", [])
        config = {"configurable": {"thread_id": thread_id or initial["task_id"]}}
        self._emit_event("RUN_STARTED", {"task_id": initial["task_id"], "requirement": initial.get("requirement", "")})
        result = await self.graph.ainvoke(initial, config=config)
        if "__interrupt__" in result:
            self._emit_event("WAITING_REVIEW", {
                "task_id": initial["task_id"],
                "verdict": result.get("final_verdict", "NEEDS_REVIEW"),
                "interrupt": result["__interrupt__"],
                "repair_history": result.get("repair_history", []),
            })
        else:
            self._emit_event("RUN_COMPLETED", {
                "task_id": initial["task_id"],
                "final_verdict": result.get("final_verdict", "UNKNOWN"),
                "repair_history": result.get("repair_history", []),
            })
        return result

    async def resume(self, thread_id: str, decision: str) -> AgentState:
        """Resume a paused human-review run using the same checkpoint thread."""
        if decision.lower() not in {"approve", "reject"}:
            raise ValueError("Human decision must be approve or reject")
        await self._ensure_async_checkpoint()
        config = {"configurable": {"thread_id": thread_id}}
        self._emit_event("RUN_RESUMED", {"task_id": thread_id, "decision": decision.lower()})
        result = await self.graph.ainvoke(Command(resume=decision.lower()), config=config)
        self._emit_event("RUN_COMPLETED", {
            "task_id": thread_id,
            "final_verdict": result.get("final_verdict", "UNKNOWN"),
            "repair_history": result.get("repair_history", []),
        })
        return result

    def _build_graph(self, checkpointer: Any):
        builder = StateGraph(AgentState)
        builder.add_node("plan", self._plan_node)
        builder.add_node("grounding_plan", self._grounding_plan_node)
        builder.add_node("retrieve", self._retrieve_node)
        builder.add_node("evidence_build", self._evidence_build_node)
        builder.add_node("generate", self._generate_node)
        builder.add_node("claim_bind", self._claim_bind_node)
        builder.add_node("code_quality", self._code_quality_node)
        builder.add_node("execute", self._execute_node)
        builder.add_node("analyze_failure", self._analyze_failure_node)
        builder.add_node("repair_grounding", self._repair_grounding_node)
        builder.add_node("repair", self._repair_node)
        builder.add_node("review", self._review_node)
        builder.add_node("persist", self._persist_node)

        builder.add_edge(START, "plan")
        builder.add_edge("plan", "grounding_plan")
        builder.add_edge("grounding_plan", "retrieve")
        builder.add_edge("retrieve", "evidence_build")
        builder.add_edge("evidence_build", "generate")
        builder.add_edge("generate", "claim_bind")
        builder.add_edge("claim_bind", "code_quality")

        builder.add_conditional_edges(
            "code_quality",
            self._route_after_code_quality,
            {"execute": "execute", "analyze_failure": "analyze_failure", "review": "review"},
        )
        builder.add_conditional_edges(
            "execute",
            self._route_after_execute,
            {"review": "review", "analyze_failure": "analyze_failure"},
        )
        builder.add_conditional_edges(
            "analyze_failure",
            self._route_after_analysis,
            {"repair": "repair_grounding", "review": "review"},
        )
        builder.add_edge("repair_grounding", "repair")
        builder.add_edge("repair", "claim_bind")
        builder.add_edge("review", "persist")
        builder.add_edge("persist", END)
        return builder.compile(checkpointer=checkpointer)

    async def _grounding_plan_node(self, state: AgentState) -> AgentState:
        res = await grounding_plan_node(state)
        return self._record(state, "grounding_plan", res)

    async def _evidence_build_node(self, state: AgentState) -> AgentState:
        res = await evidence_build_node(state)
        return self._record(state, "evidence_build", res)

    async def _claim_bind_node(self, state: AgentState) -> AgentState:
        res = await claim_bind_node(state)
        return self._record(state, "claim_bind", res)

    async def _repair_grounding_node(self, state: AgentState) -> AgentState:
        res = await repair_grounding_node(state)
        new_state = self._record(state, "repair_grounding", res)
        # Actively retrieve additional evidence for formulated repair queries if retriever is present
        repair_plan = res.get("repair_plan", {})
        queries = repair_plan.get("queries", [])
        if queries and self.retriever:
            repair_query_plan = {
                "plan_id": f"repair_{state.get('repair_round', 0) + 1}",
                "queries": queries,
            }
            temp_state = {**new_state, "grounding_query_plan": repair_query_plan}
            try:
                repair_context = await _maybe_call(self.retriever, temp_state)
                if repair_context:
                    combined_context = list(new_state.get("retrieved_context", [])) + list(repair_context)
                    builder = EvidenceCatalogBuilder(pinned_commit=new_state.get("pinned_commit"))
                    bundle = builder.build_bundle(
                        extracted_records=[
                            r for r in new_state.get("evidence_catalog", [])
                            if isinstance(r, EvidenceRecord)
                        ],
                        retrieved_items=combined_context,
                        query_plan=repair_query_plan,
                    )
                    update: AgentState = {
                        "retrieved_context": combined_context,
                        "evidence_catalog": bundle.evidence,
                        "grounding_coverage_score": bundle.coverage_score,
                    }
                    new_state = {**new_state, **update}
            except Exception as ex:
                logger.warning("Failed active retrieval in repair_grounding_node: %s", ex)
        return new_state

    async def _plan_node(self, state: AgentState) -> AgentState:
        result = await _maybe_call(self.planner, state)
        return self._record(state, "plan", {"test_plan": result})

    async def _retrieve_node(self, state: AgentState) -> AgentState:
        context = await _maybe_call(self.retriever, state)
        evidence_items: list[dict[str, Any]] = []
        if isinstance(context, list):
            for item in context:
                if isinstance(item, dict) and "evidence_id" in item and "kind" in item and "value" in item:
                    evidence_items.append(item)
                elif hasattr(item, "evidence_id") and hasattr(item, "kind") and hasattr(item, "value"):
                    evidence_items.append({
                        "evidence_id": getattr(item, "evidence_id"),
                        "kind": getattr(item, "kind"),
                        "value": getattr(item, "value"),
                        "source": getattr(item, "source", "catalog"),
                        "confidence": getattr(item, "confidence", 1.0),
                    })
        update: AgentState = {"retrieved_context": context}
        if evidence_items:
            update["grounding_catalog"] = evidence_items
        return self._record(state, "retrieve", update)

    async def _generate_node(self, state: AgentState) -> AgentState:
        ws = state.get("workspace") or state.get("workspace_dir") or ""
        files = await _maybe_call(self.generator, state)
        write_result = await self.tools.invoke("write_files", workspace=ws, files=files)
        update: AgentState = {
            "generated_files": files,
            "initial_generated_files": dict(files),
            "generation_success": write_result.ok,
        }
        if "used_evidence_ids" in state:
            update["used_evidence_ids"] = list(state["used_evidence_ids"])
        if not write_result.ok:
            update["error"] = write_result.error
        return self._record(state, "generate", update, {"write_files": write_result.as_dict()})

    async def _code_quality_node(self, state: AgentState) -> AgentState:
        files = state.get("generated_files", {})
        req = state.get("requirement", "")
        target = state.get("target_entrypoint")
        context = state.get("retrieved_context", [])
        ws = state.get("workspace") or state.get("workspace_dir") or state.get("repo_path")
        catalog = state.get("grounding_catalog")

        gate_res: CodeQualityGateResult = await self.code_quality_gate.evaluate(
            generated_files=files,
            requirement=req,
            target_entrypoint=target,
            retrieved_context=context,
            evidence_catalog=catalog,
            repo_path=ws,
            previous_files=state.get("previous_generated_files"),
            baseline_files=state.get("initial_generated_files"),
        )

        history_entry = {
            "round": state.get("repair_round", 0),
            "status": gate_res.status,
            "vacuity_score": gate_res.vacuity_score,
            "grounding_score": gate_res.grounding_score,
            "violations_count": len(gate_res.hard_violations),
            "weakening_detected": gate_res.weakening_detected,
            "timestamp": time.time(),
        }
        cq_history = [*state.get("code_quality_history", []), history_entry]

        update: AgentState = {
            "code_quality_result": gate_res.as_dict(),
            "code_quality_history": cq_history,
            "vacuity_score": gate_res.vacuity_score,
            "grounding_score": gate_res.grounding_score,
            "weakening_detected": gate_res.weakening_detected,
        }

        # If quality gate rejected and we cannot execute, surface error or diagnostics
        if gate_res.status == "REJECTED" and not gate_res.allow_execution:
            update["execution_success"] = False
            update["execution_result"] = {
                "passed": False,
                "exit_code": 1,
                "stdout": "",
                "stderr": "\n".join(gate_res.repair_feedback),
            }

        return self._record(state, "code_quality", update)

    async def _execute_node(self, state: AgentState) -> AgentState:
        ws = state.get("workspace") or state.get("workspace_dir") or ""
        framework = state.get("framework") or state.get("test_framework") or "pytest"
        cmd = state.get("test_command") or (["pytest", "-v", "tests"] if framework == "pytest" else ["npm", "test"])
        result = await self.tools.invoke(
            "run_tests", workspace=ws, command=cmd,
            framework=framework, task_id=state.get("task_id"),
        )
        execution = result.data if result.ok else {"passed": False, "error": result.error}
        passed = bool(execution.get("passed"))
        update: AgentState = {"execution_result": execution, "execution_success": passed}
        if "first_execution_result" not in state:
            update["first_execution_result"] = execution

        # Backfill outcome for the latest repair round if it was pending
        history = [dict(entry) for entry in state.get("repair_history", [])]
        if history and history[-1].get("re_execution_passed") is None:
            history[-1]["re_execution_passed"] = passed
            history[-1]["exit_code"] = execution.get("exit_code")
            history[-1]["duration_ms"] = execution.get("duration_ms", 0.0)
            update["repair_history"] = history

        return self._record(state, "execute", update, {"run_tests": result.as_dict()})

    async def _analyze_failure_node(self, state: AgentState) -> AgentState:
        execution = state.get("execution_result", {})
        output = f"{execution.get('stdout', '')}\n{execution.get('stderr', '')}"
        failed_tests = re.findall(r"(?:FAILED|ERROR)\s+([^\s:]+)", output)

        # Merge code quality repair feedback if present
        cq_feedback = state.get("code_quality_result", {}).get("repair_feedback", [])
        if cq_feedback:
            output += "\n=== CODE QUALITY GATE VIOLATIONS ===\n" + "\n".join(cq_feedback)

        analysis = {
            "root_cause": self._classify_failure(output),
            "failed_tests": list(dict.fromkeys(failed_tests)),
            "evidence": output[-10_000:],
        }
        return self._record(state, "analyze_failure", {"failure_analysis": analysis})

    async def _repair_node(self, state: AgentState) -> AgentState:
        ws = state.get("workspace") or state.get("workspace_dir") or ""
        before_files = dict(state.get("generated_files", {}))

        # 1. Build canonical EvidenceCatalog2 for repair plan validation
        catalog_records = []
        for r in state.get("evidence_catalog", []):
            if isinstance(r, EvidenceRecord):
                catalog_records.append(r)
            elif isinstance(r, dict):
                try:
                    d = dict(r)
                    d.setdefault("extractor", "extracted")
                    catalog_records.append(EvidenceRecord(**d))
                except Exception:
                    pass
        catalog = EvidenceCatalog2(catalog_records)

        # 2. Formulate structured RepairPlan BEFORE repair
        failure = state.get("failure_analysis", {})
        state_repair_plan = state.get("repair_plan")

        if isinstance(state_repair_plan, RepairPlan):
            plan_obj = state_repair_plan
        elif isinstance(state_repair_plan, dict) and state_repair_plan:
            plan_obj = RepairPlan(
                root_cause=state_repair_plan.get("root_cause", failure.get("root_cause", "execution_failure")),
                proposed_changes=state_repair_plan.get("proposed_changes", []),
                expectation_changes=state_repair_plan.get("expectation_changes", []),
                required_evidence_ids=state_repair_plan.get("required_evidence_ids", state.get("used_evidence_ids", [])),
            )
        else:
            expectation_changes = []
            if state.get("weakening_detected"):
                expectation_changes.append("revert_weakened_assertions")
            root_cause = failure.get("root_cause", "execution_failure")
            plan_obj = RepairPlan(
                root_cause=root_cause,
                proposed_changes=[
                    RepairChange(
                        change_type="alter_expectation" if expectation_changes else "fix_sut_call",
                        target="test_logic",
                        description=f"Repair failure caused by {root_cause}",
                        evidence_id=catalog_records[0].evidence_id if catalog_records else None,
                    )
                ],
                expectation_changes=expectation_changes,
                required_evidence_ids=state.get("used_evidence_ids", [r.evidence_id for r in catalog_records[:3]]),
            )

        # 3. Strictly validate RepairPlan with RepairGroundingPlanner BEFORE invoking repair
        validated_plan = RepairGroundingPlanner.validate_repair_plan(plan_obj, catalog)
        if not validated_plan.allow_repair:
            round_num = state.get("repair_round", 0) + 1
            update: AgentState = {
                "repair_round": round_num,
                "repair_rejected": True,
                "repair_plan": validated_plan.model_dump(),
                "error": validated_plan.rejection_reason,
            }
            logger.warning("Repair plan rejected before invocation: %s", validated_plan.rejection_reason)
            return self._record(state, "repair", update)

        # 4. Invoke repairer with validated structured plan
        state_with_plan = {**state, "repair_plan": validated_plan.model_dump()}
        repaired_files = await _maybe_call(self.repairer, state_with_plan)

        write_result = await self.tools.invoke("write_files", workspace=ws, files=repaired_files)
        round_num = state.get("repair_round", 0) + 1

        files_diff = {}
        all_names = set(before_files.keys()) | set(repaired_files.keys())
        for name in sorted(all_names):
            before_code = before_files.get(name, "")
            proposed_code = repaired_files.get(name, "")
            if before_code == proposed_code:
                continue
            diff_lines = list(difflib.unified_diff(
                before_code.splitlines(),
                proposed_code.splitlines(),
                fromfile=f"a/{name}" if name in before_files else "/dev/null",
                tofile=f"b/{name}" if name in repaired_files else "/dev/null",
                lineterm=""
            ))
            files_diff[name] = {
                "before_code": before_code,
                "proposed_code": proposed_code,
                "diff": "\n".join(diff_lines),
            }

        history_entry = {
            "round": round_num,
            "failure_type": failure.get("root_cause", "unknown"),
            "failed_tests": failure.get("failed_tests", []),
            "failure_evidence": failure.get("evidence", "")[-4000:],
            "files": files_diff,
            "re_execution_passed": None,
            "exit_code": None,
            "duration_ms": None,
        }
        initial_files = state.get("initial_generated_files") or before_files
        repair_history = [*state.get("repair_history", []), history_entry]
        update: AgentState = {
            "generated_files": repaired_files,
            "initial_generated_files": initial_files,
            "previous_generated_files": before_files,
            "repair_round": round_num,
            "repair_history": repair_history,
            "repair_plan": validated_plan.model_dump(),
        }
        if not write_result.ok:
            update["error"] = write_result.error
        return self._record(state, "repair", update, {"write_files": write_result.as_dict()})

    async def _review_node(self, state: AgentState) -> AgentState:
        review = await _maybe_call(self.reviewer, state)
        execution = state.get("execution_result", {})
        exec_passed = bool(execution.get("passed", False))
        cq_res = state.get("code_quality_result", {})
        cq_status = cq_res.get("status", "PASS")
        rev_status = review.get("status", "uncertain")

        # Stage 5 Hard Invariant: final PASS requires:
        # 1. Execution PASS
        # 2. Code quality PASS and no weakening detected
        # 3. Semantic review PASS
        # 4. No blocking evidence conflicts
        # 5. No unsupported claims (0 hallucination)
        # 6. No unindexed core business facts (api_endpoint, target_symbol, model_field) in unknown_claims
        # 7. Grounding coverage >= 0.80
        # 8. Provenance completeness == True
        # 9. Grounded claim rate >= 0.95
        # 10. Repair was not rejected for ungrounded changes
        has_blocking_conflict = any(
            isinstance(c, dict) and c.get("severity") == "blocking"
            for c in state.get("evidence_conflicts", [])
        )
        unsupported = state.get("unsupported_claims", [])
        unknown_claims = state.get("unknown_claims", [])
        core_unknowns = [
            c for c in unknown_claims
            if isinstance(c, dict) and c.get("kind") in ("api_endpoint", "target_symbol", "model_field")
        ]
        has_core_unknowns = len(core_unknowns) > 0

        cov_val = state.get("grounding_coverage_score")
        if cov_val is None:
            bundle_dict = state.get("evidence_bundle")
            if isinstance(bundle_dict, dict):
                cov_val = bundle_dict.get("coverage_score", 0.0)
            else:
                cov_val = 0.0
        coverage_score = float(cov_val)

        prov_val = state.get("provenance_completeness")
        if prov_val is None:
            bundle_dict = state.get("evidence_bundle")
            if isinstance(bundle_dict, dict):
                prov_val = bundle_dict.get("provenance_complete", False)
            else:
                prov_val = False
        provenance_complete = bool(prov_val)

        g_rate = state.get("grounded_claim_rate")
        grounded_claim_rate = float(g_rate) if g_rate is not None else 0.0
        weakening_detected = state.get("weakening_detected", False)
        repair_rejected = state.get("repair_rejected", False)

        if not exec_passed:
            exit_code = execution.get("exit_code")
            verdict = "REJECTED" if exit_code not in (0, None) else "NEEDS_REVIEW"
        elif cq_status == "REJECTED" or rev_status == "fail" or unsupported or weakening_detected or repair_rejected:
            verdict = "REJECTED"
        elif (
            cq_status == "NEEDS_REVIEW"
            or has_blocking_conflict
            or has_core_unknowns
            or coverage_score < 0.80
            or not provenance_complete
            or grounded_claim_rate < 0.95
        ):
            verdict = "NEEDS_REVIEW"
        elif rev_status == "uncertain":
            verdict = "NEEDS_REVIEW"
        else:
            verdict = "PASS"

        first_execution = state.get("first_execution_result", execution)
        repair_success = bool(
            not first_execution.get("passed") and exec_passed and verdict == "PASS"
        )

        update: AgentState = {
            "review": review,
            "final_verdict": verdict,
            "repair_success": repair_success,
        }

        if state.get("human_review") and verdict != "PASS" and not state.get("human_decision"):
            decision = interrupt({
                "task_id": state.get("task_id"),
                "reason": f"Automated quality gate did not produce a PASS verdict (current verdict: {verdict}).",
                "verdict": verdict,
                "review": review,
                "code_quality": cq_res,
            })
            update["human_decision"] = str(decision)
            update["final_verdict"] = "MANUAL_APPROVED" if str(decision).lower() == "approve" else "REJECTED"

        return self._record(state, "review", update)

    async def _persist_node(self, state: AgentState) -> AgentState:
        updated = self._record(state, "persist", {})
        if state.get("trace_path"):
            TraceRecorder(state["trace_path"]).write_run(updated)

        # Stage 5 Relational Evidence Persistence in SQLite
        db_path = state.get("evidence_db_path")
        if not db_path and state.get("workspace"):
            db_path = str(Path(state["workspace"]) / "evidence.sqlite")
        elif not db_path and state.get("trace_path"):
            db_path = str(Path(state["trace_path"]).parent / "evidence.sqlite")

        if db_path:
            try:
                repo = EvidenceRepository(db_path)
                for ev in state.get("evidence_catalog", []):
                    record: Optional[EvidenceRecord] = None
                    if isinstance(ev, EvidenceRecord):
                        record = ev
                    elif isinstance(ev, dict) and "evidence_id" in ev:
                        try:
                            d = dict(ev)
                            d.setdefault("extractor", "extracted")
                            record = EvidenceRecord(**d)
                        except Exception:
                            pass

                    if record:
                        # 1. Persist SourceManifest (source)
                        manifest = SourceManifest(
                            source_id=record.source_id,
                            repository=record.repo_url,
                            commit_sha=record.commit_sha,
                            path=record.source_path,
                            file_type=Path(record.source_path).suffix.lstrip(".") if record.source_path else "code",
                            content_hash=record.content_hash,
                        )
                        repo.save_manifest(manifest)

                        # 2. Persist SourceChunk (chunk)
                        chunk = SourceChunk(
                            chunk_id=record.source_chunk_id,
                            source_id=record.source_id,
                            text=record.value,
                            line_start=record.line_start or 1,
                            line_end=record.line_end or (record.line_start or 1),
                            content_hash=record.content_hash,
                        )
                        repo.save_chunk(chunk)

                        # 3. Persist EvidenceRecord (evidence)
                        repo.save_evidence_record(record)

                # 4. Persist ClaimEvidenceBinding (claim & claim_evidence_links)
                for cb in state.get("claim_bindings", []):
                    if isinstance(cb, ClaimEvidenceBinding):
                        repo.save_claim_binding(cb)
                    elif isinstance(cb, dict) and "claim_id" in cb:
                        try:
                            repo.save_claim_binding(ClaimEvidenceBinding(**cb))
                        except Exception:
                            pass
            except Exception as ex:
                logger.warning("Failed to persist evidence repository to %s: %s", db_path, ex)

        return updated

    def _route_after_code_quality(self, state: AgentState) -> Literal["execute", "analyze_failure", "review"]:
        cq_res = state.get("code_quality_result", {})
        # If code quality permits execution (even with warnings or valid tests), execute
        if cq_res.get("allow_execution", True):
            return "execute"
        # If execution forbidden (e.g. syntax error or only fake tests)
        if state.get("repair_round", 0) < state.get("max_repair_rounds", 2):
            return "analyze_failure"
        return "review"

    def _route_after_execute(self, state: AgentState) -> Literal["review", "analyze_failure"]:
        return "review" if state.get("execution_result", {}).get("passed") else "analyze_failure"

    def _route_after_analysis(self, state: AgentState) -> Literal["repair", "review"]:
        if state.get("repair_round", 0) < state.get("max_repair_rounds", 2):
            return "repair"
        return "review"

    def _record(self, state: AgentState, node: str, update: AgentState,
                tools: dict[str, Any] | None = None) -> AgentState:
        event = {"node": node, "task_id": state.get("task_id"), "tools": tools or {}}
        if node == "retrieve":
            context = update.get("retrieved_context", [])
            event["retrieval"] = {
                "count": len(context),
                "sources": [item.get("source") for item in context if item.get("source")],
                "ids": [item.get("id") for item in context if item.get("id")],
            }
        new_state = {**state, **update, "trace": [*state.get("trace", []), event]}

        # Emit observability event
        payload = {
            "node": node,
            "task_id": state.get("task_id"),
            "repair_round": new_state.get("repair_round", 0),
        }
        if node == "execute":
            exec_res = new_state.get("execution_result", {})
            payload["passed"] = exec_res.get("passed", False)
            payload["exit_code"] = exec_res.get("exit_code")
            payload["duration_ms"] = exec_res.get("duration_ms", 0.0)
            payload["stdout"] = exec_res.get("stdout", "")
            payload["stderr"] = exec_res.get("stderr", "")
        elif node == "code_quality":
            cq_res = new_state.get("code_quality_result", {})
            payload["status"] = cq_res.get("status")
            payload["vacuity_score"] = cq_res.get("vacuity_score", 1.0)
            payload["grounding_score"] = cq_res.get("grounding_score", 1.0)
            payload["violations"] = cq_res.get("hard_violations", [])
            payload["unsupported_claims"] = cq_res.get("grounding_findings", [])
        elif node == "generate":
            payload["files"] = list(new_state.get("generated_files", {}).keys())
        elif node == "repair":
            history = new_state.get("repair_history", [])
            if history:
                payload["latest_repair"] = history[-1]
        elif node == "review":
            payload["verdict"] = new_state.get("final_verdict")
        elif node == "analyze_failure":
            payload["failure_analysis"] = new_state.get("failure_analysis")

        self._emit_event(f"{node.upper()}_COMPLETED", payload)
        return new_state

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        if not self.event_sink:
            return
        payload = {"event": event_type, "timestamp": time.time(), **data}
        try:
            res = self.event_sink(payload)
            if inspect.isawaitable(res):
                asyncio.create_task(res)
        except Exception as e:
            logger.warning("Error in event sink: %s", e)

    @staticmethod
    def _default_planner(state: AgentState) -> dict[str, Any]:
        return {"goal": state.get("requirement", ""), "steps": ["generate", "code_quality", "execute", "review"]}

    @staticmethod
    def _default_generator(state: AgentState) -> dict[str, str]:
        return dict(state.get("generated_files", {}))

    @staticmethod
    def _default_retriever(state: AgentState) -> list[dict[str, Any]]:
        return list(state.get("retrieved_context", []))

    @staticmethod
    def _default_repairer(state: AgentState) -> dict[str, str]:
        return dict(state.get("generated_files", {}))

    @staticmethod
    def _default_reviewer(state: AgentState) -> dict[str, Any]:
        return {"status": "pass" if state.get("execution_result", {}).get("passed") else "uncertain"}

    @staticmethod
    def _classify_failure(output: str) -> str:
        lowered = output.lower()
        if "assert" in lowered:
            return "assertion_failure"
        if "modulenotfounderror" in lowered or "cannot find module" in lowered:
            return "missing_dependency"
        if "timeout" in lowered or "timed out" in lowered:
            return "timeout"
        if "syntaxerror" in lowered:
            return "syntax_error"
        return "runtime_or_environment_failure"

    @staticmethod
    def _write_files(workspace: str, files: dict[str, str]) -> list[str]:
        return WorkspaceArtifacts(workspace).write_files(files)

    async def _run_tests(self, workspace: str, command: list[str], framework: str, task_id: str | None = None) -> dict[str, Any]:
        executor = create_test_executor(
            workspace,
            backend=self.execution_backend,
            policy=self.sandbox_policy,
            task_id=task_id,
        )
        return await asyncio.to_thread(executor.run, command, framework=framework)


def build_agentic_workflow(**kwargs: Any) -> AgenticTestWorkflow:
    """Factory kept as a stable integration point for the CLI and tests."""
    return AgenticTestWorkflow(**kwargs)
