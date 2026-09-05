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

    def __init__(self, generator: RAGEnhancedTestGenerator, test_cases: list[TestCase],
                 llm_manager: LLMManager) -> None:
        self.generator = generator
        self.test_cases = test_cases
        self.llm_manager = llm_manager

    def planner(self, state: AgentState) -> dict[str, Any]:
        return {
            "goal": state.get("requirement", "Generate and validate automation tests"),
            "test_case_ids": [case.id for case in self.test_cases],
            "steps": ["retrieve_context", "generate", "execute", "repair_on_failure", "review"],
        }

    async def retrieve(self, state: AgentState) -> list[dict[str, Any]]:
        query = state.get("requirement") or " ".join(case.objective for case in self.test_cases)
        result = await self.generator.knowledge_extractor.vector_store.query_collection(
            query, n_results=self.generator.num_context_docs
        )
        return [
            {
                "id": item.get("id"),
                "content": item.get("document", ""),
                "metadata": item.get("metadata", {}),
                "distance": item.get("distance"),
                "source": item.get("metadata", {}).get("source")
                or item.get("metadata", {}).get("file_path"),
            }
            for item in result
        ]

    async def generate(self, state: AgentState) -> dict[str, str]:
        return await self.generator.generate(self.test_cases)

    async def repair(self, state: AgentState) -> dict[str, str]:
        files = dict(state.get("generated_files", {}))
        failure = state.get("failure_analysis", {})
        for name, code in list(files.items()):
            if not name.endswith((".py", ".js", ".ts", ".java")):
                continue
            prompt = f"""Repair this generated test file using only the observed failure.

FAILURE TYPE: {failure.get('root_cause', 'unknown')}
FAILED TESTS: {failure.get('failed_tests', [])}
EXECUTION EVIDENCE:
{failure.get('evidence', '')[-8000:]}

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


def build_existing_rag_workflow(generator: RAGEnhancedTestGenerator,
                                test_cases: list[TestCase],
                                llm_manager: LLMManager,
                                checkpoint_path: str | None = None,
                                event_sink: Any = None,
                                execution_backend: str = "auto") -> AgenticTestWorkflow:
    adapter = ExistingRAGAdapter(generator, test_cases, llm_manager)
    return AgenticTestWorkflow(
        planner=adapter.planner,
        retriever=adapter.retrieve,
        generator=adapter.generate,
        repairer=adapter.repair,
        reviewer=adapter.reviewer,
        checkpoint_path=checkpoint_path,
        event_sink=event_sink,
        execution_backend=execution_backend,
    )

