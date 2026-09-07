"""LangGraph nodes for Stage 5 RAG Grounding, Evidence Building, and Claim Binding."""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from pathlib import Path

from testteller.core.evidence.catalog import EvidenceCatalog2
from testteller.core.evidence.catalog_builder import EvidenceCatalogBuilder
from testteller.core.evidence.chunking import LineAwareChunker
from testteller.core.evidence.extractors import (
    OpenAPIEvidenceExtractor,
    PythonASTEvidenceExtractor,
)
from testteller.core.evidence.ids import (
    compute_chunk_id,
    compute_content_hash,
    compute_source_id,
    normalize_relative_path,
)
from testteller.core.evidence.models import EvidenceRecord, SourceChunk, SourceManifest
from testteller.core.retrieval.query_planner import GroundingQueryPlanner
from testteller.quality_gate.claim_binding import ClaimEvidenceBinder
from testteller.quality_gate.grounding import CodeClaimExtractor
from testteller.automator_agent.repair_planner import RepairGroundingPlanner
from .state import AgentState

logger = logging.getLogger(__name__)


async def grounding_plan_node(state: AgentState) -> Dict[str, Any]:
    """Analyze requirement and formulate structured GroundingQueryPlan."""
    req = state.get("requirement", "")
    target_ep = state.get("target_entrypoint")
    planner = GroundingQueryPlanner()
    plan = planner.plan(requirement_text=req, target_entrypoint=target_ep)

    event_payload = {
        "type": "GROUNDING_PLAN_COMPLETED",
        "plan_id": plan.plan_id,
        "query_count": len(plan.queries),
        "kinds": list(dict.fromkeys(q.kind for q in plan.queries)),
    }
    logger.info("Grounding plan formulated: %s (%d sub-queries)", plan.plan_id, len(plan.queries))

    plan_dict = {
        "plan_id": plan.plan_id,
        "queries": [
            {
                "query_id": q.query_id,
                "kind": q.kind,
                "text": q.text,
                "required": q.required,
                "exact_terms": q.exact_terms,
            }
            for q in plan.queries
        ],
        "requirement_text": req,
        "target_entrypoint": target_ep,
    }
    return {
        "grounding_query_plan": plan_dict,
        "trace": state.get("trace", []) + [event_payload],
    }


async def evidence_build_node(state: AgentState) -> Dict[str, Any]:
    """Extract deterministic facts, aggregate with retrieved context, and resolve conflicts."""
    target_repo = state.get("target_repo") or state.get("repo_path") or state.get("workspace", "")
    target_ep = state.get("target_entrypoint")
    pinned_commit = state.get("pinned_commit")
    if not pinned_commit:
        if target_repo and Path(target_repo).exists():
            try:
                import subprocess
                res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=target_repo,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0 and res.stdout.strip():
                    pinned_commit = res.stdout.strip()
            except Exception:
                pinned_commit = None
        if not pinned_commit:
            try:
                import subprocess
                res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0 and res.stdout.strip():
                    pinned_commit = res.stdout.strip()
            except Exception:
                pinned_commit = None

    extracted: List[EvidenceRecord] = []
    for ev in state.get("evidence_catalog", []):
        if isinstance(ev, EvidenceRecord):
            extracted.append(ev)
        elif isinstance(ev, dict):
            try:
                d = dict(ev)
                d.setdefault("extractor", "extracted")
                extracted.append(EvidenceRecord(**d))
            except Exception:
                pass

    native_manifests: List[SourceManifest] = []
    native_chunks: List[SourceChunk] = []
    chunker = LineAwareChunker()

    # 1. Native Ingestion & AST extraction if target_repo exists
    if target_repo and Path(target_repo).exists():
        ast_extractor = PythonASTEvidenceExtractor()
        repo_path = Path(target_repo)
        # Scan top-level py files or target entrypoint
        for py_file in repo_path.glob("**/*.py"):
            if any(part.startswith((".", "venv", "build", "tests")) for part in py_file.parts):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                rel_path = normalize_relative_path(str(py_file.relative_to(repo_path)))
                source_id = compute_source_id(str(repo_path), pinned_commit, rel_path)
                f_hash = compute_content_hash(content)
                manifest = SourceManifest(
                    source_id=source_id,
                    repository=str(repo_path),
                    commit_sha=pinned_commit,
                    path=rel_path,
                    file_type="python",
                    content_hash=f_hash,
                )
                native_manifests.append(manifest)
                f_chunks = chunker.chunk_text(content, source_id=source_id, file_type="python")
                native_chunks.extend(f_chunks)

                file_records = ast_extractor.extract_from_code(
                    code=content,
                    file_path=rel_path,
                    repository=str(repo_path),
                    commit_sha=pinned_commit,
                )
                extracted.extend(file_records)
                for rec in file_records:
                    if rec.source_chunk_id and not any(c.chunk_id == rec.source_chunk_id for c in native_chunks):
                        c_lines = content.splitlines(keepends=True)[rec.line_start - 1 : rec.line_end] if (rec.line_start and rec.line_end) else []
                        c_text = "".join(c_lines) or rec.value
                        native_chunks.append(
                            SourceChunk(
                                chunk_id=rec.source_chunk_id,
                                source_id=source_id,
                                text=c_text,
                                line_start=rec.line_start or 1,
                                line_end=rec.line_end or 1,
                                content_hash=rec.content_hash,
                            )
                        )
            except Exception as ex:
                logger.debug("Failed extracting from %s: %s", py_file, ex)

        # Scan for OpenAPI JSON/YAML specs
        openapi_extractor = OpenAPIEvidenceExtractor()
        for spec_file in list(repo_path.glob("**/openapi.yaml")) + list(repo_path.glob("**/openapi.json")) + list(repo_path.glob("**/openapi.yml")):
            try:
                content = spec_file.read_text(encoding="utf-8", errors="replace")
                rel_path = normalize_relative_path(str(spec_file.relative_to(repo_path)))
                source_id = compute_source_id(str(repo_path), pinned_commit, rel_path)
                f_hash = compute_content_hash(content)
                f_type = spec_file.suffix.lstrip(".") or "yaml"
                manifest = SourceManifest(
                    source_id=source_id,
                    repository=str(repo_path),
                    commit_sha=pinned_commit,
                    path=rel_path,
                    file_type=f_type,
                    content_hash=f_hash,
                )
                native_manifests.append(manifest)
                f_chunks = chunker.chunk_text(content, source_id=source_id, file_type="text")
                native_chunks.extend(f_chunks)

                spec_records = openapi_extractor.extract_from_file(
                    spec_file,
                    commit_sha=pinned_commit,
                )
                extracted.extend(spec_records)
            except Exception as ex:
                logger.debug("Failed extracting from %s: %s", spec_file, ex)

    # 2. Build EvidenceBundle with both extracted records and retrieved context
    retrieved_items = state.get("retrieved_context", [])
    builder = EvidenceCatalogBuilder(pinned_commit=pinned_commit)
    bundle = builder.build_bundle(
        extracted_records=extracted,
        retrieved_items=retrieved_items,
        query_plan=state.get("grounding_query_plan"),
    )

    trace = list(state.get("trace", []))
    trace.append({
        "type": "EVIDENCE_CATALOG_BUILT",
        "evidence_count": len(bundle.evidence),
        "coverage_score": bundle.coverage_score,
        "conflict_count": len(bundle.conflicts),
        "provenance_complete": bundle.provenance_complete,
    })

    if bundle.conflicts:
        trace.append({
            "type": "EVIDENCE_CONFLICT_DETECTED",
            "conflicts": [
                {
                    "conflict_id": c.conflict_id,
                    "kind": c.kind,
                    "subject": c.subject,
                    "severity": c.severity,
                }
                for c in bundle.conflicts
            ],
        })

    return {
        "evidence_bundle": {
            "coverage_score": bundle.coverage_score,
            "provenance_complete": bundle.provenance_complete,
            "conflict_count": len(bundle.conflicts),
        },
        "evidence_catalog": bundle.evidence,
        "evidence_conflicts": [
            {
                "conflict_id": c.conflict_id,
                "kind": c.kind,
                "subject": c.subject,
                "severity": c.severity,
                "resolution": c.resolution,
            }
            for c in bundle.conflicts
        ],
        "grounding_coverage_score": bundle.coverage_score,
        "provenance_completeness": bundle.provenance_complete,
        "source_manifests": [m.model_dump() for m in native_manifests] + list(state.get("source_manifests", [])),
        "source_chunks": [c.model_dump() for c in native_chunks] + list(state.get("source_chunks", [])),
        "trace": trace,
    }


async def claim_bind_node(state: AgentState) -> Dict[str, Any]:
    """Extract claims from generated tests and bind them to verified EvidenceRecords."""
    files = state.get("generated_files", {})
    target_ep = state.get("target_entrypoint")
    all_claims = []

    # 1. Extract AST claims from all generated test files
    for file_path, code in files.items():
        if not file_path.endswith((".py",)):
            continue
        try:
            import ast
            tree = ast.parse(code, filename=file_path)
            extractor = CodeClaimExtractor(file_path=file_path, target_entrypoint=target_ep)
            extractor.visit(tree)
            all_claims.extend(extractor.claims)
        except Exception:
            pass

    # 2. Build EvidenceCatalog2 from state
    ev_items = state.get("evidence_catalog", [])
    records = []
    for item in ev_items:
        if isinstance(item, EvidenceRecord):
            records.append(item)
        elif isinstance(item, dict):
            try:
                records.append(EvidenceRecord(**item))
            except Exception:
                pass
    catalog = EvidenceCatalog2(records)

    # 3. Extract claimed citations from inline annotations and used_evidence_ids
    claimed_citations_set = set(state.get("used_evidence_ids", []))
    import re
    for file_path, code in files.items():
        found = re.findall(r"#\s*@cite\s+([A-Za-z0-9_\-]+)", code)
        claimed_citations_set.update(found)
    claimed_citations = list(claimed_citations_set)

    # 4. Bind claims to evidence
    result = ClaimEvidenceBinder.bind(
        claims=all_claims,
        catalog=catalog,
        claimed_citations=claimed_citations,
        target_entrypoint=target_ep,
    )

    trace = list(state.get("trace", []))
    trace.append({
        "type": "CLAIM_BINDING_COMPLETED",
        "claims_count": len(result.bindings),
        "grounded_claim_rate": result.grounded_claim_rate,
        "citation_accuracy": result.citation_accuracy,
        "citation_coverage": getattr(result, "citation_coverage", 1.0),
        "unsupported_count": len(result.unsupported_claims),
        "unknown_count": len(result.unknown_claims),
    })

    return {
        "claim_bindings": [b.model_dump() for b in result.bindings],
        "grounding_manifest": result.grounding_manifest,
        "grounded_claim_rate": result.grounded_claim_rate,
        "citation_accuracy": result.citation_accuracy,
        "citation_coverage": getattr(result, "citation_coverage", 1.0),
        "unsupported_claims": [b.model_dump() for b in result.unsupported_claims],
        "unknown_claims": [b.model_dump() for b in result.unknown_claims],
        "trace": trace,
    }



async def repair_grounding_node(state: AgentState) -> Dict[str, Any]:
    """Formulate targeted grounding queries on test failure to support evidence-backed repair."""
    failure = state.get("failure_analysis", {})
    evidence_text = failure.get("evidence", "")
    queries = RepairGroundingPlanner.formulate_repair_queries(evidence_text)

    trace = list(state.get("trace", []))
    trace.append({
        "type": "REPAIR_GROUNDING_COMPLETED",
        "queries_count": len(queries),
    })

    return {
        "repair_plan": {
            "root_cause": failure.get("root_cause", "unknown"),
            "queries": [
                {
                    "query_id": q.query_id,
                    "kind": q.kind,
                    "text": q.text,
                    "exact_terms": q.exact_terms,
                }
                for q in queries
            ],
        },
        "trace": trace,
    }
