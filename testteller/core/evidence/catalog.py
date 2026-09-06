"""Evidence Catalog 2.0 managing verified EvidenceRecords with bidirectional index (Stage 5.3)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ids import normalize_endpoint_path, normalize_evidence_value
from .models import EvidenceKind, EvidenceRecord, TrustLevel

logger = logging.getLogger(__name__)


class EvidenceCatalog2:
    """Canonical repository of machine-verified evidence records for grounding validation."""

    def __init__(self, records: Optional[Iterable[EvidenceRecord]] = None):
        self._records_by_id: Dict[str, EvidenceRecord] = {}
        self._records_by_kind: Dict[str, List[EvidenceRecord]] = {
            "api_endpoint": [],
            "ui_selector": [],
            "model_field": [],
            "target_symbol": [],
            "config": [],
            "auth_pattern": [],
            "requirement": [],
            "test_pattern": [],
            "behavior_contract": [],
        }
        self._exact_index: Dict[Tuple[str, str], EvidenceRecord] = {}

        if records:
            self.add_records(records)

    def add_record(self, record: EvidenceRecord) -> None:
        """Register an evidence record into catalog and update internal indexes."""
        self._records_by_id[record.evidence_id] = record
        if record.kind not in self._records_by_kind:
            self._records_by_kind[record.kind] = []
        self._records_by_kind[record.kind].append(record)

        norm_val = normalize_evidence_value(record.kind, record.value)
        self._exact_index[(record.kind, norm_val)] = record

    def add_records(self, records: Iterable[EvidenceRecord]) -> None:
        for r in records:
            self.add_record(r)

    def get_by_id(self, evidence_id: str) -> Optional[EvidenceRecord]:
        """Look up an evidence record by its deterministic ID."""
        return self._records_by_id.get(evidence_id)

    def get_by_kind(self, kind: str) -> List[EvidenceRecord]:
        """Retrieve all evidence records belonging to a kind."""
        return list(self._records_by_kind.get(kind, []))

    def has_domain(self, kind: str) -> bool:
        """Return True if catalog contains verified evidence for this domain."""
        return bool(self._records_by_kind.get(kind))

    def all_records(self) -> List[EvidenceRecord]:
        return list(self._records_by_id.values())

    def find_match(self, kind: str, value: str) -> Optional[EvidenceRecord]:
        """
        Attempt to find a verified EvidenceRecord supporting the given kind and value.
        Supports exact match and domain-specific template/symbol matching.
        """
        norm_val = normalize_evidence_value(kind, value)
        key = (kind, norm_val)
        if key in self._exact_index:
            return self._exact_index[key]

        if kind == "api_endpoint":
            return self._match_api_endpoint(value)
        elif kind == "target_symbol":
            return self._match_target_symbol(value)
        elif kind == "model_field":
            return self._match_model_field(value)

        return None

    def _match_api_endpoint(self, claim_val: str) -> Optional[EvidenceRecord]:
        parts = claim_val.strip().split(maxsplit=1)
        if len(parts) != 2:
            return None
        c_method, c_path = parts[0].upper(), normalize_endpoint_path(parts[1])

        for ev in self._records_by_kind.get("api_endpoint", []):
            ev_parts = ev.value.strip().split(maxsplit=1)
            if len(ev_parts) == 2:
                e_method, e_path = ev_parts[0].upper(), normalize_endpoint_path(ev_parts[1])
                if c_method == e_method:
                    if c_path == e_path or self._path_matches_template(template=e_path, concrete=c_path):
                        return ev
            elif len(ev_parts) == 1:
                e_path = normalize_endpoint_path(ev_parts[0])
                if c_path == e_path or self._path_matches_template(template=e_path, concrete=c_path):
                    return ev
        return None

    def _match_target_symbol(self, claim_val: str) -> Optional[EvidenceRecord]:
        c_val = claim_val.strip()
        short_c_val = c_val.split(".")[-1]

        for ev in self._records_by_kind.get("target_symbol", []):
            if ev.value == c_val:
                return ev
            ev_short = ev.value.split(".")[-1]
            if short_c_val == ev_short:
                return ev
        return None

    def _match_model_field(self, claim_val: str) -> Optional[EvidenceRecord]:
        c_val = claim_val.strip()
        short_c_val = c_val.split(".")[-1]

        for ev in self._records_by_kind.get("model_field", []):
            if ev.value == c_val:
                return ev
            ev_short = ev.value.split(".")[-1]
            if short_c_val == ev_short:
                return ev
        return None

    @staticmethod
    def _path_matches_template(template: str, concrete: str) -> bool:
        """Check if concrete path matches parameterized template like /users/{id}."""
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
        pattern = f"^{pattern}$"
        try:
            return bool(re.match(pattern, concrete))
        except re.error:
            return False

    def to_legacy_catalog(self) -> Any:
        """Convert to Stage 4 EvidenceCatalog for backward compatibility."""
        from testteller.quality_gate.grounding import EvidenceCatalog
        legacy = EvidenceCatalog()
        for r in self._records_by_id.values():
            legacy.add_item(r.to_legacy_evidence_item())
        return legacy

    @classmethod
    def from_legacy_catalog(
        cls,
        legacy_catalog: Any,
        default_commit: str = "",
    ) -> EvidenceCatalog2:
        """Create an EvidenceCatalog2 from a Stage 4 EvidenceCatalog."""
        catalog = cls()
        for item in legacy_catalog.get_items():
            ev = EvidenceRecord(
                evidence_id=item.evidence_id,
                kind=item.kind,
                value=item.value,
                source_id=f"SRC-{item.source}",
                source_path=item.source,
                source_chunk_id=f"CHK-{item.evidence_id}",
                commit_sha=default_commit,
                content_hash="",
                extractor="legacy_bridge",
                trust_level=TrustLevel.T0_AUTHORITATIVE,
                confidence=item.confidence,
            )
            catalog.add_record(ev)
        return catalog
