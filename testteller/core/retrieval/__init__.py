"""Hybrid retrieval primitives for local and vector-backed project knowledge."""

from .hybrid_retriever import HybridRetriever
from .local_index import LocalIndex
from .models import RetrievalResult

__all__ = ["HybridRetriever", "LocalIndex", "RetrievalResult"]
