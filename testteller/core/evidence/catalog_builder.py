"""Evidence Catalog Builder assembling canonical EvidenceBundle instances (Stage 5.3)."""

from __future__ import annotations

import logging
from typing import Any, List, Optional
from .catalog import EvidenceCatalog2
from .conflicts import ConflictResolver
from .models import EvidenceBundle, EvidenceConflict, EvidenceRecord, TrustLevel
from ..retrieval.models import RetrievalItem

logger = logging.getLogger(__name__)


class EvidenceCatalogBuilder:
    """Builds canonical EvidenceBundle from retrieved chunks, extracted facts, and OpenAPI specs."""

    def __init__(self, pinned_commit: Optional[str] = None):
        self.pinned_commit = pinned_commit
        self.resolver = ConflictResolver(pinned_commit=pinned_commit)

    def build_bundle(
        self,
        retrieved_items: Optional[List[RetrievalItem]] = None,
        extracted_records: Optional[List[EvidenceRecord]] = None,
        query_plan: Optional[Any] = None,
    ) -> EvidenceBundle:
        """Aggregate evidence, resolve conflicts, calculate coverage, and output EvidenceBundle."""
        all_records: List[EvidenceRecord] = []

        # 1. Include explicitly extracted records (AST, OpenAPI)
        if extracted_records:
            all_records.extend(extracted_records)

        # 2. Convert retrieved chunks or evidence items from retrieval
        if retrieved_items:
            for item in retrieved_items:
                # If item is an EvidenceRecord already
                if isinstance(item, EvidenceRecord):
                    all_records.append(item)
                    continue

                # If item is a dict with evidence_id/kind/value (from app_context.to_evidence_items())
                if isinstance(item, dict) and "kind" in item and "value" in item and ("evidence_id" in item or "id" in item):
                    ev_id = item.get("evidence_id") or item.get("id") or ""
                    meta = item.get("metadata", {})
                    all_records.append(
                        EvidenceRecord(
                            evidence_id=ev_id,
                            kind=item.get("kind"),
                            value=item.get("value"),
                            source_id=meta.get("source_id", f"src_{item.get('source', 'unknown')}"),
                            source_path=item.get("source", "unknown"),
                            source_chunk_id=meta.get("chunk_id", f"chk_{ev_id}"),
                            line_start=meta.get("line_start"),
                            line_end=meta.get("line_end"),
                            commit_sha=meta.get("commit_sha"),
                            content_hash=meta.get("content_hash", ""),
                            extractor=meta.get("extractor", "knowledge_extractor"),
                            trust_level=TrustLevel.T1_STRONG,
                            confidence=item.get("confidence", 1.0),
                        )
                    )
                    continue

                # If item is a RetrievalItem or dict representing a retrieved document chunk
                if isinstance(item, dict):
                    meta = item.get("metadata") or {}
                    chunk_id = item.get("chunk_id") or item.get("id") or "chk_unknown"
                    src = item.get("source") or meta.get("source") or meta.get("file_path") or "unknown"
                    content = item.get("content") or ""
                    match_rules = item.get("match_rules") or []
                else:
                    meta = getattr(item, "metadata", None) or {}
                    chunk_id = getattr(item, "chunk_id", "chk_unknown")
                    src = getattr(item, "source", "unknown") or meta.get("source") or "unknown"
                    content = getattr(item, "content", "")
                    match_rules = getattr(item, "match_rules", [])

                source_id = meta.get("source_id") or f"src_{src}"
                commit_sha = meta.get("commit_sha")
                content_hash = meta.get("content_hash") or ""
                doc_type = meta.get("type", "code")

                # If retrieved item has exact match rules (e.g. symbol:Foo or api_key:GET /users)
                for rule in match_rules:
                    if ":" in rule:
                        rule_type, rule_val = rule.split(":", 1)
                        kind = "target_symbol" if "symbol" in rule_type else (
                            "api_endpoint" if "api" in rule_type else "config"
                        )
                        ev = EvidenceRecord(
                            evidence_id=f"evi_{kind}_{chunk_id[-8:] if len(chunk_id)>=8 else chunk_id}",
                            kind=kind,
                            value=rule_val,
                            source_id=source_id,
                            source_path=src,
                            source_chunk_id=chunk_id,
                            line_start=meta.get("line_start"),
                            line_end=meta.get("line_end"),
                            commit_sha=commit_sha,
                            content_hash=content_hash,
                            extractor="hybrid_retriever",
                            trust_level=TrustLevel.T1_STRONG if doc_type == "code" else TrustLevel.T2_SUPPORTING,
                        )
                        all_records.append(ev)

        # 3. Conflict Detection and Authority Resolution
        retained_records, conflicts = self.resolver.detect_and_resolve(all_records)

        # 4. Provenance completeness check
        provenance_complete = True
        for r in retained_records:
            if not r.source_id or not r.source_chunk_id or not r.source_path:
                provenance_complete = False
                break

        # 5. Calculate coverage against query plan if provided
        coverage_score = 1.0
        missing: List[str] = []
        if query_plan and hasattr(query_plan, "queries"):
            required_queries = [q for q in query_plan.queries if getattr(q, "required", True)]
            if required_queries:
                catalog = EvidenceCatalog2(retained_records)
                matched_count = 0
                for q in required_queries:
                    found = False
                    for term in getattr(q, "exact_terms", [getattr(q, "text", "")]):
                        if catalog.find_match(q.kind, term):
                            found = True
                            break
                    if found:
                        matched_count += 1
                    else:
                        missing.append(f"{q.kind}:{getattr(q, 'text', '')}")
                coverage_score = round(matched_count / len(required_queries), 4)

        return EvidenceBundle(
            query_plan=query_plan,
            evidence=retained_records,
            conflicts=conflicts,
            missing_required_evidence=missing,
            coverage_score=coverage_score,
            provenance_complete=provenance_complete,
        )
