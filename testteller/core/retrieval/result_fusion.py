"""Rank fusion and deduplication for local and vector retrieval results."""

from .models import RetrievalItem


def fuse_results(local_items: list[RetrievalItem], vector_items: list[RetrievalItem], limit: int) -> list[RetrievalItem]:
    """Use RRF rather than mixing incompatible rule scores and vector distances."""
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
        local_rrf = 1.0 / (60 + item.local_rank) if item.local_rank else 0.0
        vector_rrf = 1.0 / (60 + item.vector_rank) if item.vector_rank else 0.0
        return exact_bonus + local_rrf + vector_rrf

    ranked = sorted(merged.values(), key=score, reverse=True)[:limit]
    for rank, item in enumerate(ranked, 1):
        item.final_rank = rank
    return ranked
