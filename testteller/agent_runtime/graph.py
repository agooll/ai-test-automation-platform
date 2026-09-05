"""LangGraph orchestration for a bounded test generation and repair loop."""

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
from .tools import AgentToolRegistry, SafeTestExecutor, SandboxPolicy, WorkspaceArtifacts, create_test_executor
from .trace import TraceRecorder

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
        self.tools = tool_registry or AgentToolRegistry()
        self.event_sink = event_sink
        self.execution_backend = execution_backend
        self.sandbox_policy = sandbox_policy
        self._register_tools()

        self._checkpoint_store = None
        self._async_checkpoint_store = None
        self._checkpoint_path = checkpoint_path
        if checkpointer is None and checkpoint_path:
            # AsyncSqliteSaver is initialized lazily because its connection is async.
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
        builder.add_node("retrieve", self._retrieve_node)
        builder.add_node("generate", self._generate_node)
        builder.add_node("execute", self._execute_node)
        builder.add_node("analyze_failure", self._analyze_failure_node)
        builder.add_node("repair", self._repair_node)
        builder.add_node("review", self._review_node)
        builder.add_node("persist", self._persist_node)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "retrieve")
        builder.add_edge("retrieve", "generate")
        builder.add_edge("generate", "execute")
        builder.add_conditional_edges("execute", self._route_after_execute,
                                      {"review": "review", "analyze_failure": "analyze_failure"})
        builder.add_conditional_edges("analyze_failure", self._route_after_analysis,
                                      {"repair": "repair", "review": "review"})
        builder.add_edge("repair", "execute")
        builder.add_edge("review", "persist")
        builder.add_edge("persist", END)
        return builder.compile(checkpointer=checkpointer)

    async def _plan_node(self, state: AgentState) -> AgentState:
        result = await _maybe_call(self.planner, state)
        return self._record(state, "plan", {"test_plan": result})

    async def _generate_node(self, state: AgentState) -> AgentState:
        files = await _maybe_call(self.generator, state)
        write_result = await self.tools.invoke("write_files", workspace=state["workspace"], files=files)
        update: AgentState = {"generated_files": files, "generation_success": write_result.ok}
        if not write_result.ok:
            update["error"] = write_result.error
        return self._record(state, "generate", update, {"write_files": write_result.as_dict()})

    async def _retrieve_node(self, state: AgentState) -> AgentState:
        context = await _maybe_call(self.retriever, state)
        return self._record(state, "retrieve", {"retrieved_context": context})

    async def _execute_node(self, state: AgentState) -> AgentState:
        result = await self.tools.invoke(
            "run_tests", workspace=state["workspace"], command=state["test_command"],
            framework=state.get("framework", "pytest"), task_id=state.get("task_id"),
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
        analysis = {
            "root_cause": self._classify_failure(output),
            "failed_tests": list(dict.fromkeys(failed_tests)),
            "evidence": output[-10_000:],
        }
        return self._record(state, "analyze_failure", {"failure_analysis": analysis})

    async def _repair_node(self, state: AgentState) -> AgentState:
        before_files = dict(state.get("generated_files", {}))
        repaired_files = await _maybe_call(self.repairer, state)
        write_result = await self.tools.invoke("write_files", workspace=state["workspace"], files=repaired_files)
        round_num = state.get("repair_round", 0) + 1

        # Compute unified diffs for all modified, added, or deleted files
        failure = state.get("failure_analysis", {})
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
        repair_history = [*state.get("repair_history", []), history_entry]
        update: AgentState = {
            "generated_files": repaired_files,
            "repair_round": round_num,
            "repair_history": repair_history,
        }
        if not write_result.ok:
            update["error"] = write_result.error
        return self._record(state, "repair", update, {"write_files": write_result.as_dict()})

    async def _review_node(self, state: AgentState) -> AgentState:
        review = await _maybe_call(self.reviewer, state)
        execution = state.get("execution_result", {})
        verdict = "PASS" if execution.get("passed") else "NEEDS_REVIEW"
        first_execution = state.get("first_execution_result", execution)
        repair_success = bool(not first_execution.get("passed") and execution.get("passed"))
        placeholder_files = [
            name for name, content in state.get("generated_files", {}).items()
            if "TODO" in content or "FIXME" in content
        ]
        if placeholder_files:
            review.setdefault("issues", []).append({
                "code": "PLACEHOLDER_CODE",
                "message": "Generated output still contains TODO/FIXME placeholders.",
                "files": placeholder_files,
            })
            verdict = "REJECTED"
        if review.get("status") == "fail":
            verdict = "REJECTED"
        update: AgentState = {
            "review": review, "final_verdict": verdict, "repair_success": repair_success,
        }
        if state.get("human_review") and verdict != "PASS" and not state.get("human_decision"):
            decision = interrupt({
                "task_id": state.get("task_id"),
                "reason": "Automated review did not produce a PASS verdict.",
                "verdict": verdict,
                "review": review,
            })
            update["human_decision"] = str(decision)
            update["final_verdict"] = "MANUAL_APPROVED" if str(decision).lower() == "approve" else "REJECTED"
        return self._record(state, "review", update)

    async def _persist_node(self, state: AgentState) -> AgentState:
        updated = self._record(state, "persist", {})
        if state.get("trace_path"):
            TraceRecorder(state["trace_path"]).write_run(updated)
        return updated

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
        return {"goal": state.get("requirement", ""), "steps": ["generate", "execute", "review"]}

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
