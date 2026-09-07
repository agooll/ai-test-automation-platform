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

    def __init__(
        self,
        pinned_commit: Optional[str] = None,
        resolver: Optional[ConflictResolver] = None,
        conflict_resolver: Optional[ConflictResolver] = None,
    ):
        self.pinned_commit = pinned_commit
        self.resolver = resolver or conflict_resolver or ConflictResolver(pinned_commit=pinned_commit)


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

                # If item is a dict with evidence_id/kind/value (from app_context.to_evidence_items() or dict)
                if isinstance(item, dict) and "kind" in item and "value" in item and ("evidence_id" in item or "id" in item):
                    ev_id = item.get("evidence_id") or item.get("id") or ""
                    meta = item.get("metadata", {})
                    src_path = item.get("source_path") or item.get("source") or meta.get("source_path") or meta.get("source", "")

                    src_id = item.get("source_id") or meta.get("source_id", "")
                    src_chunk = item.get("source_chunk_id") or item.get("chunk_id") or meta.get("chunk_id", "")
                    line_s = item.get("line_start") if item.get("line_start") is not None else meta.get("line_start")
                    line_e = item.get("line_end") if item.get("line_end") is not None else meta.get("line_end")
                    commit = item.get("commit_sha") or meta.get("commit_sha") or ""
                    c_hash = item.get("content_hash") or meta.get("content_hash", "")
                    extractor = item.get("extractor") or meta.get("extractor", "knowledge_extractor")

                    has_canonical_prov = bool(
                        commit
                        and c_hash
                        and (line_s is not None and line_s > 0)
                        and (src_chunk and src_chunk != "chk_unknown")
                        and src_id
                        and src_path
                        and not src_path.startswith("discovered:")
                        and src_path != "unknown"
                    )

                    raw_trust = item.get("trust_level") or meta.get("trust_level")
                    parsed_trust = None
                    if raw_trust:
                        try:
                            parsed_trust = raw_trust if isinstance(raw_trust, TrustLevel) else TrustLevel(raw_trust)
                        except Exception:
                            parsed_trust = None

                    # Strict T1 promotion rule: Only items with canonical provenance can be T0/T1
                    if has_canonical_prov:
                        if parsed_trust in (TrustLevel.T0_AUTHORITATIVE, TrustLevel.T1_STRONG):
                            trust = parsed_trust
                        else:
                            trust = parsed_trust or TrustLevel.T1_STRONG
                    else:
                        if parsed_trust in (TrustLevel.T0_AUTHORITATIVE, TrustLevel.T1_STRONG):
                            trust = TrustLevel.T2_SUPPORTING
                        else:
                            trust = parsed_trust or (
                                TrustLevel.T3_WEAK if (not src_path or src_path.startswith("discovered:")) else TrustLevel.T2_SUPPORTING
                            )


                    all_records.append(
                        EvidenceRecord(
                            evidence_id=ev_id,
                            kind=item.get("kind"),
                            value=item.get("value"),
                            source_id=src_id,
                            source_path=src_path,
                            source_chunk_id=src_chunk,
                            line_start=line_s,
                            line_end=line_e,
                            commit_sha=commit,
                            content_hash=c_hash,
                            extractor=extractor,
                            trust_level=trust,
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

                source_id = meta.get("source_id") or ""
                commit_sha = meta.get("commit_sha") or ""
                content_hash = meta.get("content_hash") or ""
                doc_type = meta.get("type", "code")

                has_retrieval_canonical_prov = bool(
                    commit_sha
                    and content_hash
                    and (meta.get("line_start") is not None and meta.get("line_start") > 0)
                    and (chunk_id and chunk_id != "chk_unknown")
                    and source_id
                    and src
                    and not src.startswith("discovered:")
                    and src != "unknown"
                )

                # If retrieved item has exact match rules (e.g. symbol:Foo or api_key:GET /users)
                for rule in match_rules:
                    if ":" in rule:
                        rule_type, rule_val = rule.split(":", 1)
                        kind = "target_symbol" if "symbol" in rule_type else (
                            "api_endpoint" if "api" in rule_type else "config"
                        )
                        trust = TrustLevel.T1_STRONG if (doc_type == "code" and has_retrieval_canonical_prov) else TrustLevel.T2_SUPPORTING
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
                            trust_level=trust,
                        )
                        all_records.append(ev)

        # 3. Conflict Detection and Authority Resolution
        retained_records, conflicts = self.resolver.detect_and_resolve(all_records)

        # 4. Provenance completeness check: commit/hash/line/chunk/source full chain
        # ZERO SYNTHESIS: If metadata lacks commit, chunk, hash, line, or source -> provenance incomplete
        if not retained_records:
            provenance_complete = False
        else:
            provenance_complete = True
            for r in retained_records:
                has_commit = bool(r.commit_sha and str(r.commit_sha).strip())
                has_hash = bool(r.content_hash and str(r.content_hash).strip())
                has_line = r.line_start is not None and r.line_start > 0
                has_chunk = bool(r.source_chunk_id and str(r.source_chunk_id).strip() and r.source_chunk_id != "chk_unknown")
                has_source = bool(
                    r.source_id
                    and r.source_path
                    and str(r.source_id).strip()
                    and str(r.source_path).strip()
                    and not r.source_path.startswith("discovered:")
                    and r.source_path != "unknown"
                )
                if not (has_commit and has_hash and has_line and has_chunk and has_source):
                    provenance_complete = False
                    break


        # 5. Calculate coverage against query plan (supports GroundingQueryPlan or dict, no fake 1.0)
        coverage_score = 0.0
        missing: List[str] = []
        raw_queries: List[Any] = []
        if query_plan:
            if isinstance(query_plan, dict):
                raw_queries = query_plan.get("queries", [])
            elif hasattr(query_plan, "queries"):
                raw_queries = getattr(query_plan, "queries", [])

        if raw_queries:
            required_queries = []
            for q in raw_queries:
                req_val = q.get("required", True) if isinstance(q, dict) else getattr(q, "required", True)
                if req_val:
                    required_queries.append(q)

            if required_queries:
                catalog = EvidenceCatalog2(retained_records)
                matched_count = 0
                for q in required_queries:
                    kind = q.get("kind", "") if isinstance(q, dict) else getattr(q, "kind", "")
                    text = q.get("text", "") if isinstance(q, dict) else getattr(q, "text", "")
                    exact_terms = q.get("exact_terms") if isinstance(q, dict) else getattr(q, "exact_terms", None)
                    if not exact_terms:
                        exact_terms = [text] if text else []

                    found = False
                    for term in exact_terms:
                        if catalog.find_match(kind, term):
                            found = True
                            break
                    if found:
                        matched_count += 1
                    else:
                        missing.append(f"{kind}:{text}")
                coverage_score = round(matched_count / len(required_queries), 4)

        return EvidenceBundle(
            query_plan=query_plan,
            evidence=retained_records,
            conflicts=conflicts,
            missing_required_evidence=missing,
            coverage_score=coverage_score,
            provenance_complete=provenance_complete,
        )
