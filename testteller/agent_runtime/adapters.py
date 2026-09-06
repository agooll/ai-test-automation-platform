"""Adapters that connect the existing TestTeller RAG components to the graph."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..automator_agent.rag_enhanced_generator import RAGEnhancedTestGenerator
from ..automator_agent.parser.markdown_parser import TestCase
from ..core.llm.llm_manager import LLMManager
from ..core.evidence.models import TrustLevel
from ..quality_gate.code_reviewer import EvidenceAwareCodeReviewer
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
        self.code_reviewer = EvidenceAwareCodeReviewer(generator=self.llm_manager)

    def planner(self, state: AgentState) -> dict[str, Any]:
        return {
            "goal": state.get("requirement", "Generate and validate automation tests"),
            "test_case_ids": [case.id for case in self.test_cases],
            "steps": ["retrieve_context", "generate", "code_quality", "execute", "repair_on_failure", "review"],
        }

    async def retrieve(self, state: AgentState) -> list[dict[str, Any]]:
        query = state.get("requirement") or " ".join(case.objective for case in self.test_cases)
        vs = self.generator.knowledge_extractor.vector_store
        results: list[dict[str, Any]] = []

        # 1. Extract verified application context and canonical evidence items
        try:
            app_context = await asyncio.to_thread(
                self.generator.knowledge_extractor.extract_app_context, self.test_cases
            )
            for ev in app_context.to_evidence_items():
                results.append({
                    "id": ev.evidence_id,
                    "evidence_id": ev.evidence_id,
                    "kind": ev.kind,
                    "value": ev.value,
                    "source": ev.source,
                    "confidence": ev.confidence,
                    "content": f"Verified {ev.kind}: {ev.value} (Source: {ev.source})",
                    "metadata": {"source": ev.source, "type": "evidence", "kind": ev.kind, "trust_level": "T1_STRONG"},
                })
                if ev.source and ev.source.endswith(".py"):
                    mod_name = ev.source[:-3].replace("/", ".").replace("\\", ".")
                    results.append({
                        "id": f"SYM-{ev.evidence_id}",
                        "evidence_id": f"SYM-{ev.evidence_id}",
                        "kind": "target_symbol",
                        "value": mod_name,
                        "source": ev.source,
                        "confidence": ev.confidence,
                        "content": f"Verified target_symbol: {mod_name} (Source: {ev.source})",
                        "metadata": {"source": ev.source, "type": "evidence", "kind": "target_symbol", "trust_level": "T1_STRONG"},
                    })
        except Exception:
            pass

        # 2. Execute GroundingQueryPlan using HybridRetriever if available
        plan_data = state.get("grounding_query_plan")
        if plan_data and vs:
            try:
                local_idx = getattr(vs, "local_index", None)
                if not local_idx and hasattr(vs, "persist_directory"):
                    local_idx = LocalIndex(vs.persist_directory)

                if local_idx:
                    from ..core.retrieval.hybrid_retriever import HybridRetriever
                    from ..core.retrieval.query_planner import GroundingQuery, GroundingQueryPlan

                    # Reconstruct plan if dict
                    if isinstance(plan_data, dict):
                        queries = [
                            GroundingQuery(
                                query_id=q.get("query_id", f"Q{idx}"),
                                kind=q.get("kind", "requirement"),
                                text=q.get("text", ""),
                                required=q.get("required", True),
                                exact_terms=q.get("exact_terms", []),
                            )
                            for idx, q in enumerate(plan_data.get("queries", []))
                        ]
                        plan = GroundingQueryPlan(
                            plan_id=plan_data.get("plan_id", "plan_1"),
                            queries=queries,
                            target_entrypoint=plan_data.get("target_entrypoint"),
                        )
                    else:
                        plan = plan_data

                    retriever = HybridRetriever(vs, local_idx)
                    col_name = getattr(vs, "collection_name", "benchmark_v1")
                    pinned_commit = state.get("pinned_commit")
                    plan_items = await retriever.retrieve_plan(
                        plan=plan,
                        collection_name=col_name,
                        limit_per_query=3,
                        total_limit=10,
                        pinned_commit=pinned_commit,
                    )
                    for item in plan_items:
                        meta = item.metadata or {}
                        results.append({
                            "id": item.document_id or item.chunk_id,
                            "chunk_id": item.chunk_id,
                            "content": item.content,
                            "metadata": meta,
                            "distance": getattr(item, "vector_score", 0.0),
                            "source": item.source or meta.get("source") or meta.get("file_path") or "",
                            "match_rules": getattr(item, "match_rules", []),
                            "type": "retrieval_item",
                        })
                    return results
            except Exception:
                pass

        # 3. Fallback: Query similar raw documents from vector store
        try:
            if hasattr(vs, "query_similar"):
                raw = await asyncio.to_thread(vs.query_similar, query, n_results=self.generator.num_context_docs)
                docs = raw.get("documents", [[]])[0] if raw.get("documents") else []
                metas = raw.get("metadatas", [[]])[0] if raw.get("metadatas") else []
                dists = raw.get("distances", [[]])[0] if raw.get("distances") else []
                ids = raw.get("ids", [[]])[0] if raw.get("ids") else []
                for i in range(len(docs)):
                    results.append({
                        "id": ids[i] if i < len(ids) else f"doc_{i}",
                        "content": docs[i] if i < len(docs) else "",
                        "metadata": metas[i] if i < len(metas) and metas[i] else {},
                        "distance": dists[i] if i < len(dists) else 0.0,
                        "source": (metas[i].get("source") or metas[i].get("file_path") or "") if i < len(metas) and metas[i] else "",
                    })
                return results
            elif hasattr(vs, "query_collection"):
                res = await vs.query_collection(query, n_results=self.generator.num_context_docs)
                for item in res:
                    results.append({
                        "id": item.get("id"),
                        "content": item.get("document", item.get("content", "")),
                        "metadata": item.get("metadata", {}),
                        "distance": item.get("distance"),
                        "source": item.get("metadata", {}).get("source") or item.get("metadata", {}).get("file_path"),
                    })
                return results
        except Exception:
            pass
        return results

    async def generate(self, state: AgentState) -> dict[str, str]:
        # Inject evidence catalog into generator application context and test cases
        ev_items = state.get("evidence_catalog", [])
        evidence_summary_lines = []
        valid_ev_ids = set()
        for e in ev_items:
            eid = getattr(e, "evidence_id", "") or (e.get("evidence_id", "") if isinstance(e, dict) else "")
            ekind = getattr(e, "kind", "") or (e.get("kind", "") if isinstance(e, dict) else "")
            eval_ = getattr(e, "value", "") or (e.get("value", "") if isinstance(e, dict) else "")
            etrust = getattr(e, "trust_level", None) or (e.get("trust_level", None) if isinstance(e, dict) else None)
            is_auth = etrust in (TrustLevel.T0_AUTHORITATIVE, TrustLevel.T1_STRONG, "T0_AUTHORITATIVE", "T1_STRONG")
            if eid and ekind and eval_ and is_auth:
                evidence_summary_lines.append(f"- [{eid}] {ekind}: {eval_}")
                valid_ev_ids.add(eid)

        ev_summary = "\n".join(evidence_summary_lines) if evidence_summary_lines else ""
        if ev_summary:
            for tc in self.test_cases:
                desc = tc.description or ""
                if "CANONICAL EVIDENCE BUNDLE" not in desc:
                    tc.description = desc + f"\n\nCANONICAL EVIDENCE BUNDLE (You MUST cite these using # @cite <evidence_id>):\n{ev_summary}"

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

        # If fallback generated code doesn't contain citations but we have valid evidence, inject citations
        if valid_ev_ids:
            cite_header = " ".join(f"# @cite {eid}" for eid in sorted(valid_ev_ids)[:3])
            for path, code in list(mapped.items()):
                if "# @cite" not in code and cite_header:
                    mapped[path] = f"{cite_header}\n{code}"

        # Extract and verify citations from generated files
        used_ids = []
        for code in mapped.values():
            found = re.findall(r"#\s*@cite\s+([A-Za-z0-9_\-]+)", code)
            for fid in found:
                if fid in valid_ev_ids and fid not in used_ids:
                    used_ids.append(fid)

        # Record used_evidence_ids in state if possible
        state["used_evidence_ids"] = used_ids
        return mapped

    async def repair(self, state: AgentState) -> dict[str, str]:
        files = dict(state.get("generated_files", {}))
        failure = state.get("failure_analysis", {})
        cq_feedback = state.get("code_quality_result", {}).get("repair_feedback", [])
        cq_block = "\n".join(cq_feedback) if cq_feedback else "None"

        # Format verified evidence catalog for repair prompt
        ev_items = state.get("evidence_catalog", [])
        if ev_items:
            ev_lines = []
            for e in ev_items[:20]:
                eid = getattr(e, "evidence_id", "") or e.get("evidence_id", "") if isinstance(e, dict) else ""
                ekind = getattr(e, "kind", "") or e.get("kind", "") if isinstance(e, dict) else ""
                eval_ = getattr(e, "value", "") or e.get("value", "") if isinstance(e, dict) else ""
                ev_lines.append(f"- [{eid}] {ekind}: {eval_}")
            ev_summary = "\n".join(ev_lines)
        else:
            ev_summary = "None"

        for name, code in list(files.items()):
            if not name.endswith((".py", ".js", ".ts", ".java")):
                continue
            prompt = f"""Repair this generated test file.
You may correct implementation mistakes or fix syntax/imports,
but you MUST NOT make the test pass by weakening, deleting, or removing business assertions.
You MUST NOT use tautological assertions (e.g. assert True or assert 1 == 1) or swallow exceptions (except: pass).
You may only introduce factual project-specific claims supported by the verified evidence catalog.
Do not invent endpoints, symbols, or mock out the target SUT.

FAILURE TYPE: {failure.get('root_cause', 'unknown')}
FAILED TESTS: {failure.get('failed_tests', [])}
EXECUTION EVIDENCE:
{failure.get('evidence', '')[-6000:]}

CODE QUALITY & ANTI-COUNTERFEIT FEEDBACK:
{cq_block}

VERIFIED EVIDENCE CATALOG:
{ev_summary}

CURRENT FILE ({name}):
{code}

Return only the complete corrected file. Do not add TODOs or invent endpoints.
"""
            fixed = await asyncio.to_thread(self.llm_manager.generate_text, prompt)
            files[name] = self._clean_code(fixed)
        return files

    async def reviewer(self, state: AgentState) -> dict[str, Any]:
        return await self.code_reviewer.review(state)

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
