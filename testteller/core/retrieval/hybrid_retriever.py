"""Routing layer that decides when an embedding call is actually needed."""

import asyncio
import time
from typing import Any, Optional, Tuple

from .local_index import LocalIndex
from .models import MatchType, QueryIntent, RetrievalItem, RetrievalResult
from .query_analyzer import QueryAnalyzer
from .result_fusion import fuse_results


class HybridRetriever:
    def __init__(self, vector_store: Any, local_index: LocalIndex):
        self.vector_store = vector_store
        self.local_index = local_index
        self.query_analyzer = QueryAnalyzer()

    async def retrieve(self, query: str, collection_name: str, limit: int = 5) -> RetrievalResult:
        started = time.perf_counter()
        analysis = self.query_analyzer.analyze(query)
        local = await asyncio.to_thread(self.local_index.search, analysis, collection_name, limit)
        strategy, reason = self._decide_strategy(analysis.intent, local)
        vector_items: list[RetrievalItem] = []
        embedding_called = strategy in {"hybrid", "vector"}

        if embedding_called:
            raw_results = await asyncio.to_thread(self.vector_store.query_similar, query, limit)
            vector_items = self._to_vector_items(raw_results)

        if strategy == "local_exact":
            documents = local.items
        elif strategy == "not_found":
            documents = []
        elif strategy == "vector":
            documents = vector_items
        else:
            documents = fuse_results(local.items, vector_items, limit)
        return RetrievalResult(
            documents=documents, strategy=strategy, query_intent=analysis.intent,
            match_type=local.match_type, local_hit_count=len(local.items), vector_hit_count=len(vector_items),
            embedding_called=embedding_called, fallback_reason=reason,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def _decide_strategy(self, intent: QueryIntent, local_result) -> Tuple[str, Optional[str]]:
        if intent in {QueryIntent.FACT_LOOKUP, QueryIntent.LOCATE} and local_result.match_type == MatchType.EXACT and local_result.unique:
            return "local_exact", None
        if local_result.has_candidates:
            return "hybrid", "multiple_local_candidates" if not local_result.unique else "intent_requires_context"
        if local_result.exact_entity_requested and intent in {QueryIntent.FACT_LOOKUP, QueryIntent.LOCATE}:
            return "not_found", "exact_entity_not_found"
        if intent in {QueryIntent.ANALYSIS, QueryIntent.IMPACT, QueryIntent.SIMILARITY, QueryIntent.GENERATE}:
            return "vector", "no_local_match" if not local_result.has_candidates else None
        return "not_found", "no_local_match"

    def _to_vector_items(self, results: dict) -> list[RetrievalItem]:
        items = []
        ids = results.get("ids", [[]])[0] or []
        documents = results.get("documents", [[]])[0] or []
        metadatas = results.get("metadatas", [[]])[0] or []
        distances = results.get("distances", [[]])[0] or []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            items.append(RetrievalItem(
                document_id=chunk_id, chunk_id=chunk_id, source=str(metadata.get("source", "unknown")),
                content=documents[index] if index < len(documents) else "", metadata=metadata,
                vector_rank=index + 1, vector_score=distances[index] if index < len(distances) else None,
            ))
        return items
