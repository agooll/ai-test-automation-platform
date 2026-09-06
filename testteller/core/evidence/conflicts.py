"""Conflict detection and resolution for Evidence Records (Stage 5.3)."""

from __future__ import annotations

import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from .models import EvidenceConflict, EvidenceRecord, TrustLevel
from .trust import resolve_authority_winner

logger = logging.getLogger(__name__)


class ConflictResolver:
    """Detects and resolves conflicts across evidence records according to authority policy."""

    def __init__(self, pinned_commit: Optional[str] = None):
        self.pinned_commit = pinned_commit

    def detect_and_resolve(
        self,
        records: List[EvidenceRecord],
    ) -> Tuple[List[EvidenceRecord], List[EvidenceConflict]]:
        """
        Scan records for conflicts on equivalent subjects.
        Returns:
            (retained_records, conflicts_detected)
        """
        conflicts: List[EvidenceConflict] = []
        # Group by (kind, subject_key)
        groups: Dict[Tuple[str, str], List[EvidenceRecord]] = {}

        for r in records:
            subject_key = self._extract_subject_key(r)
            if subject_key:
                key = (r.kind, subject_key)
                groups.setdefault(key, []).append(r)

        retained: List[EvidenceRecord] = []
        discarded_ids: set[str] = set()

        for (kind, subject), group in groups.items():
            if len(group) <= 1:
                retained.extend(group)
                continue

            # Check if all records in group agree on value
            unique_values = {r.value for r in group}
            if len(unique_values) == 1:
                # Deduplicate identical records, keep the one with highest authority
                best = group[0]
                for other in group[1:]:
                    winner = resolve_authority_winner(best, other, self.pinned_commit)
                    if winner:
                        best = winner
                retained.append(best)
                continue

            # Real conflict: different values for same subject
            conflict_id = f"CONF-{kind[:3].upper()}-{hashlib.sha256((kind + ':' + subject).encode('utf-8')).hexdigest()[:8]}"
            ev_ids = [r.evidence_id for r in group]

            # Try resolving through authority hierarchy
            winner = group[0]
            unresolved = False
            for other in group[1:]:
                res = resolve_authority_winner(winner, other, self.pinned_commit)
                if res is None:
                    unresolved = True
                else:
                    winner = res

            if not unresolved:
                # Successfully resolved by authority
                logger.info(
                    "Resolved conflict on %s (%s) in favor of %s",
                    subject, kind, winner.evidence_id
                )
                conf = EvidenceConflict(
                    conflict_id=conflict_id,
                    kind=kind,
                    subject=subject,
                    evidence_ids=ev_ids,
                    severity="warning",
                    resolution=f"Resolved by authority in favor of {winner.evidence_id} ({winner.extractor})",
                    resolved_evidence_id=winner.evidence_id,
                )
                conflicts.append(conf)
                retained.append(winner)
                for r in group:
                    if r.evidence_id != winner.evidence_id:
                        discarded_ids.add(r.evidence_id)
            else:
                # Blocking conflict: cannot determine true winner automatically
                logger.warning(
                    "Blocking conflict detected on %s (%s) among %s",
                    subject, kind, ev_ids
                )
                conf = EvidenceConflict(
                    conflict_id=conflict_id,
                    kind=kind,
                    subject=subject,
                    evidence_ids=ev_ids,
                    severity="blocking",
                    resolution="Unresolvable conflict across sources; requires manual review",
                    resolved_evidence_id=None,
                )
                conflicts.append(conf)
                # Keep all in retained for audit, but caller will inspect blocking conflicts
                retained.extend(group)

        # Add any records that were not subject-grouped
        grouped_ids = {r.evidence_id for grp in groups.values() for r in grp}
        for r in records:
            if r.evidence_id not in grouped_ids and r.evidence_id not in discarded_ids:
                retained.append(r)

        return retained, conflicts

    def _extract_subject_key(self, record: EvidenceRecord) -> Optional[str]:
        """Extract a canonical subject key to identify potential conflicts."""
        val = record.value.strip()
        if record.kind == "api_endpoint":
            # Group by resource path ignoring version prefix or handler differences
            parts = val.split(maxsplit=1)
            if len(parts) == 2:
                path = parts[1].strip()
                # Normalize /v1/users and /v2/users to user resource subject
                resource_core = path.rstrip("/")
                for prefix in ("/api/v1", "/api/v2", "/api/v3", "/v1", "/v2", "/v3"):
                    if resource_core.startswith(prefix):
                        resource_core = resource_core[len(prefix):]
                        break
                return f"{parts[0].upper()} {resource_core}"
            return val
        elif record.kind == "model_field":
            # Group by Class.field
            return val
        elif record.kind == "target_symbol":
            # Group by short symbol name
            return val.split(".")[-1]
        elif record.kind == "config":
            return val
        return None
