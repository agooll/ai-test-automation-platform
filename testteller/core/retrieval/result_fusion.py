"""Rank fusion and deduplication for local and vector retrieval results."""

from __future__ import annotations

from typing import Optional
from .models import RetrievalItem


def fuse_results(
    local_items: list[RetrievalItem],
    vector_items: list[RetrievalItem],
    limit: int,
    pinned_commit: str | None = None,
) -> list[RetrievalItem]:
    """Use RRF with authority boost and pinned commit weighting."""
    merged: dict[str, RetrievalItem] = {}
    for item in local_items + vector_items:
        key = item.chunk_id or f"{item.document_id}:{item.source}"
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            continue
        existing.vector_rank = existing.vector_rank or item.vector_rank
        existing.vector_score = existing.vector_score if existing.vector_score is not None else item.vector_score
        existing.local_rank = existing.local_rank or item.local_rank
        existing.local_score = existing.local_score if existing.local_score is not None else item.local_score
        existing.match_rules = list(dict.fromkeys(existing.match_rules + item.match_rules))

    def score(item: RetrievalItem) -> float:
        # Exact deterministic facts are intentionally pinned above semantic neighbors.
        exact_bonus = 1.0 if item.local_score and item.local_score >= 0.98 else 0.0
        
        # Authority boost: source code and OpenAPI specifications supersede unstructured docs
        meta = item.metadata or {}
        doc_type = meta.get("type", "")
        authority_bonus = 0.25 if doc_type in ("code", "openapi") else (0.15 if doc_type in ("test", "tests") else 0.0)

        # Freshness / Pinned commit weighting
        commit = meta.get("commit_sha", "")
        pinned_bonus = 0.0
        if pinned_commit and commit:
            if commit == pinned_commit:
                pinned_bonus = 0.50
            else:
                pinned_bonus = -0.50  # Penalty for stale commit when pinned commit is specified

        local_rrf = 1.0 / (60 + item.local_rank) if item.local_rank else 0.0
        vector_rrf = 1.0 / (60 + item.vector_rank) if item.vector_rank else 0.0
        return exact_bonus + authority_bonus + pinned_bonus + local_rrf + vector_rrf

    ranked = sorted(merged.values(), key=score, reverse=True)[:limit]
    for rank, item in enumerate(ranked, 1):
        item.final_rank = rank
    return ranked
