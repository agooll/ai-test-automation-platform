"""Shared data models for the hybrid retrieval layer."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MatchType(str, Enum):
    EXACT = "exact"
    PARTIAL = "partial"
    NONE = "none"


class QueryIntent(str, Enum):
    FACT_LOOKUP = "fact_lookup"
    LOCATE = "locate"
    ANALYSIS = "analysis"
    IMPACT = "impact"
    SIMILARITY = "similarity"
    GENERATE = "generate"


@dataclass
class QueryAnalysis:
    query: str
    intent: QueryIntent
    test_ids: list[str] = field(default_factory=list)
    api_paths: list[str] = field(default_factory=list)
    api_methods: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class LocalIndexEntry:
    collection_name: str
    document_id: str
    chunk_id: str
    source: str
    content: str
    content_type: str
    keywords: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    qualified_symbols: list[str] = field(default_factory=list)
    api_paths: list[str] = field(default_factory=list)
    api_methods: list[str] = field(default_factory=list)
    api_keys: list[str] = field(default_factory=list)
    test_ids: list[str] = field(default_factory=list)
    selectors: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    content_hash: str = ""
    version: int = 1


@dataclass
class RetrievalItem:
    document_id: str
    chunk_id: str
    source: str
    content: str
    metadata: dict = field(default_factory=dict)
    local_rank: Optional[int] = None
    vector_rank: Optional[int] = None
    local_score: Optional[float] = None
    vector_score: Optional[float] = None
    match_rules: list[str] = field(default_factory=list)
    final_rank: int = 0


@dataclass
class LocalSearchResult:
    items: list[RetrievalItem] = field(default_factory=list)
    match_type: MatchType = MatchType.NONE
    unique: bool = False
    exact_entity_requested: bool = False

    @property
    def has_candidates(self) -> bool:
        return bool(self.items)


@dataclass
class RetrievalResult:
    documents: list[RetrievalItem]
    strategy: str
    query_intent: QueryIntent
    match_type: MatchType
    local_hit_count: int
    vector_hit_count: int
    embedding_called: bool
    fallback_reason: Optional[str]
    elapsed_ms: float
