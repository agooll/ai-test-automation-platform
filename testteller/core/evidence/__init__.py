"""TestTeller Evidence & Provenance subsystem (Stage 5)."""

from .models import (
    TrustLevel,
    SourceManifest,
    SourceChunk,
    EvidenceKind,
    EvidenceRecord,
    EvidenceConflict,
    EvidenceBundle,
)
from .ids import (
    compute_source_id,
    compute_chunk_id,
    compute_evidence_id,
    compute_content_hash,
    normalize_evidence_value,
    normalize_relative_path,
)
from .chunking import LineAwareChunker
from .trust import (
    can_support_factual_claim,
    resolve_authority_winner,
    KIND_AUTHORITY_WEIGHTS,
)
from .extractors import (
    PythonASTEvidenceExtractor,
    OpenAPIEvidenceExtractor,
)
from .catalog import EvidenceCatalog2
from .conflicts import ConflictResolver
from .catalog_builder import EvidenceCatalogBuilder

__all__ = [
    "TrustLevel",
    "SourceManifest",
    "SourceChunk",
    "EvidenceKind",
    "EvidenceRecord",
    "EvidenceConflict",
    "EvidenceBundle",
    "compute_source_id",
    "compute_chunk_id",
    "compute_evidence_id",
    "compute_content_hash",
    "normalize_evidence_value",
    "normalize_relative_path",
    "LineAwareChunker",
    "can_support_factual_claim",
    "resolve_authority_winner",
    "KIND_AUTHORITY_WEIGHTS",
    "PythonASTEvidenceExtractor",
    "OpenAPIEvidenceExtractor",
    "EvidenceCatalog2",
    "ConflictResolver",
    "EvidenceCatalogBuilder",
]
