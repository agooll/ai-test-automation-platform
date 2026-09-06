"""Canonical data models for Stage 5: Evidence Traceability and Provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class TrustLevel(str, Enum):
    """Trust hierarchy for evidence sources (T0 to T4)."""
    T0_AUTHORITATIVE = "T0_AUTHORITATIVE"  # OpenAPI, source code AST, router/schema definitions, pinned commit
    T1_STRONG = "T1_STRONG"                # Project test suites, generated schema, framework config
    T2_SUPPORTING = "T2_SUPPORTING"        # README, design docs, docstrings/comments
    T3_WEAK = "T3_WEAK"                    # Historical generated tests, inferred patterns
    T4_UNVERIFIED = "T4_UNVERIFIED"        # LLM inference (cannot directly support a factual claim)

    @property
    def rank(self) -> int:
        """Numeric rank for comparison (lower is more authoritative)."""
        ranks = {
            TrustLevel.T0_AUTHORITATIVE: 0,
            TrustLevel.T1_STRONG: 1,
            TrustLevel.T2_SUPPORTING: 2,
            TrustLevel.T3_WEAK: 3,
            TrustLevel.T4_UNVERIFIED: 4,
        }
        return ranks.get(self, 99)

    @property
    def is_authoritative(self) -> bool:
        """Whether this trust level can independently support a factual claim."""
        return self in (TrustLevel.T0_AUTHORITATIVE, TrustLevel.T1_STRONG)


class SourceManifest(BaseModel):
    """Manifest of an ingested source file or document."""
    model_config = ConfigDict(extra="ignore")

    source_id: str
    repository: Optional[str] = None
    commit_sha: Optional[str] = None
    path: str
    file_type: str
    content_hash: str
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SourceChunk(BaseModel):
    """A line-bounded, content-addressed slice of a source document."""
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    source_id: str
    text: str
    line_start: int
    line_end: int
    content_hash: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


EvidenceKind = Literal[
    "target_symbol",
    "api_endpoint",
    "model_field",
    "ui_selector",
    "auth_pattern",
    "config",
    "requirement",
    "test_pattern",
    "behavior_contract",
]


class EvidenceRecord(BaseModel):
    """A canonical, provenance-backed evidence record in the catalog."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    kind: EvidenceKind
    value: str
    source_id: str
    source_path: str
    source_chunk_id: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    repo_url: Optional[str] = None
    commit_sha: Optional[str] = None
    content_hash: str = ""
    extractor: str
    extractor_version: str = "1.0.0"
    trust_level: TrustLevel = TrustLevel.T0_AUTHORITATIVE
    confidence: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_legacy_evidence_item(self) -> Any:
        """Bridge to Stage 4 EvidenceItem for backward compatibility."""
        from testteller.quality_gate.code_models import EvidenceItem
        return EvidenceItem(
            evidence_id=self.evidence_id,
            kind=self.kind,
            value=self.value,
            source=self.source_path,
            confidence=self.confidence,
        )


class EvidenceConflict(BaseModel):
    """Represents a detected conflict between two or more evidence records."""
    model_config = ConfigDict(extra="ignore")

    conflict_id: str
    kind: str
    subject: str
    evidence_ids: List[str]
    severity: Literal["warning", "blocking"] = "blocking"
    resolution: Optional[str] = None
    resolved_evidence_id: Optional[str] = None


class EvidenceBundle(BaseModel):
    """A cohesive bundle of retrieved and extracted evidence for a test generation run."""
    model_config = ConfigDict(extra="ignore")

    query_plan: Optional[Any] = None
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    conflicts: List[EvidenceConflict] = Field(default_factory=list)
    missing_required_evidence: List[str] = Field(default_factory=list)
    coverage_score: float = 0.0
    provenance_complete: bool = True
