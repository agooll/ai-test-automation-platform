"""Adapters that connect the existing TestTeller RAG components to the graph."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..automator_agent.rag_enhanced_generator import RAGEnhancedTestGenerator
from ..automator_agent.parser.markdown_parser import TestCase
from ..core.llm.llm_manager import LLMManager
from .graph import AgenticTestWorkflow
from .state import AgentState


class ExistingRAGAdapter:
    """Use the repository's current RAG generator inside the agent graph."""

    def __init__(
        self,
        generator: RAGEnhancedTestGenerator,
        test_cases: list[TestCase],
        llm_manager: LLMManager,
        allow_weak_fallback: bool = False,
    ) -> None:
        self.generator = generator
        self.test_cases = test_cases
        self.llm_manager = llm_manager
        self.allow_weak_fallback = allow_weak_fallback

    def planner(self, state: AgentState) -> dict[str, Any]:
        return {
            "goal": state.get("requirement", "Generate and validate automation tests"),
            "test_case_ids": [case.id for case in self.test_cases],
            "steps": ["retrieve_context", "generate", "code_quality", "execute", "repair_on_failure", "review"],
        }

    async def retrieve(self, state: AgentState) -> list[dict[str, Any]]:
        query = state.get("requirement") or " ".join(case.objective for case in self.test_cases)
        vs = self.generator.knowledge_extractor.vector_store
        try:
            if hasattr(vs, "query_similar"):
                raw = await asyncio.to_thread(vs.query_similar, query, n_results=self.generator.num_context_docs)
                docs = raw.get("documents", [[]])[0] if raw.get("documents") else []
                metas = raw.get("metadatas", [[]])[0] if raw.get("metadatas") else []
                dists = raw.get("distances", [[]])[0] if raw.get("distances") else []
                ids = raw.get("ids", [[]])[0] if raw.get("ids") else []
                return [
                    {
                        "id": ids[i] if i < len(ids) else f"doc_{i}",
                        "content": docs[i] if i < len(docs) else "",
                        "metadata": metas[i] if i < len(metas) and metas[i] else {},
                        "distance": dists[i] if i < len(dists) else 0.0,
                        "source": (metas[i].get("source") or metas[i].get("file_path") or "") if i < len(metas) and metas[i] else "",
                    }
                    for i in range(len(docs))
                ]
            elif hasattr(vs, "query_collection"):
                res = await vs.query_collection(query, n_results=self.generator.num_context_docs)
                return [
                    {
                        "id": item.get("id"),
                        "content": item.get("document", item.get("content", "")),
                        "metadata": item.get("metadata", {}),
                        "distance": item.get("distance"),
                        "source": item.get("metadata", {}).get("source") or item.get("metadata", {}).get("file_path"),
                    }
                    for item in res
                ]
        except Exception:
            pass
        return []

    async def generate(self, state: AgentState) -> dict[str, str]:
        try:
            files = await self.generator.generate(self.test_cases)
        except Exception:
            files = {}

        if not files and self.allow_weak_fallback:
            files = self.generator._generate_fallback_files(self.test_cases)

        # Standardize paths under tests/ directory so pytest discovers them
        mapped = {}
        for k, v in files.items():
            if not k.startswith("tests/") and not k.startswith("tests\\"):
                mapped[f"tests/{k}"] = v
            else:
                mapped[k] = v
        return mapped

    async def repair(self, state: AgentState) -> dict[str, str]:
        files = dict(state.get("generated_files", {}))
        failure = state.get("failure_analysis", {})
        cq_feedback = state.get("code_quality_result", {}).get("repair_feedback", [])
        cq_block = "\n".join(cq_feedback) if cq_feedback else "None"

        for name, code in list(files.items()):
            if not name.endswith((".py", ".js", ".ts", ".java")):
                continue
            prompt = f"""Repair this generated test file.
You may correct implementation mistakes or fix syntax/imports,
but you MUST NOT make the test pass by weakening, deleting, or removing business assertions.
You MUST NOT use tautological assertions (e.g. assert True or assert 1 == 1) or swallow exceptions (except: pass).

FAILURE TYPE: {failure.get('root_cause', 'unknown')}
FAILED TESTS: {failure.get('failed_tests', [])}
EXECUTION EVIDENCE:
{failure.get('evidence', '')[-6000:]}

CODE QUALITY & ANTI-COUNTERFEIT FEEDBACK:
{cq_block}

CURRENT FILE ({name}):
{code}

Return only the complete corrected file. Do not add TODOs or invent endpoints.
"""
            fixed = await asyncio.to_thread(self.llm_manager.generate_text, prompt)
            files[name] = self._clean_code(fixed)
        return files

    @staticmethod
    def reviewer(state: AgentState) -> dict[str, Any]:
        execution = state.get("execution_result", {})
        return {
            "status": "pass" if execution.get("passed") else "uncertain",
            "evidence": {
                "exit_code": execution.get("exit_code"),
                "repair_round": state.get("repair_round", 0),
            },
        }

    @staticmethod
    def _clean_code(value: str) -> str:
        value = re.sub(r"^```\w*\s*", "", value.strip())
        value = re.sub(r"\s*```$", "", value)
        return value.strip()


def build_existing_rag_workflow(
    generator: RAGEnhancedTestGenerator,
    test_cases: list[TestCase],
    llm_manager: LLMManager,
    checkpoint_path: str | None = None,
    event_sink: Any = None,
    execution_backend: str = "auto",
    sandbox_policy: Any = None,
    code_quality_gate: Any = None,
    allow_weak_fallback: bool = False,
) -> AgenticTestWorkflow:
    adapter = ExistingRAGAdapter(
        generator=generator,
        test_cases=test_cases,
        llm_manager=llm_manager,
        allow_weak_fallback=allow_weak_fallback,
    )
    return AgenticTestWorkflow(
        planner=adapter.planner,
        retriever=adapter.retrieve,
        generator=adapter.generate,
        repairer=adapter.repair,
        reviewer=adapter.reviewer,
        code_quality_gate=code_quality_gate,
        checkpoint_path=checkpoint_path,
        event_sink=event_sink,
        execution_backend=execution_backend,
        sandbox_policy=sandbox_policy,
    )
