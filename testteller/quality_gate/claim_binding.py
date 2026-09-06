"""Claim-to-Evidence Binding and Citation Verification for Stage 5 Traceability."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from testteller.core.evidence.catalog import EvidenceCatalog2
from testteller.core.evidence.models import EvidenceRecord
from testteller.quality_gate.code_models import (
    ClaimItem,
    CodeViolation,
    CodeViolationCode,
    GroundingFinding,
)

logger = logging.getLogger(__name__)


class ClaimEvidenceBinding(BaseModel):
    """Formal binding between an extracted test claim and canonical evidence records."""
    model_config = ConfigDict(extra="ignore")

    claim_id: str
    kind: str
    value: str
    status: Literal["SUPPORTED", "UNSUPPORTED", "UNKNOWN"]
    evidence_ids: List[str] = Field(default_factory=list)
    citation_valid: bool = True
    source_file: str = ""
    line_number: Optional[int] = None
    message: str = ""
    provenance_chain: Optional[Dict[str, Any]] = None


class ClaimBindingResult(BaseModel):
    """Result of binding all claims in a generated test against verified evidence."""
    model_config = ConfigDict(extra="ignore")

    bindings: List[ClaimEvidenceBinding] = Field(default_factory=list)
    grounded_claim_rate: float = 1.0
    citation_accuracy: float = 1.0
    unsupported_claims: List[ClaimEvidenceBinding] = Field(default_factory=list)
    unknown_claims: List[ClaimEvidenceBinding] = Field(default_factory=list)
    has_blocking_violations: bool = False
    violations: List[CodeViolation] = Field(default_factory=list)
    findings: List[GroundingFinding] = Field(default_factory=list)
    grounding_manifest: Dict[str, Any] = Field(default_factory=dict)


class ClaimEvidenceBinder:
    """Binds claims to evidence, validates citations, and constructs traceability manifests."""

    @classmethod
    def bind(
        cls,
        claims: List[ClaimItem],
        catalog: Any,  # EvidenceCatalog2 or EvidenceCatalog
        claimed_citations: Optional[List[str]] = None,
        target_entrypoint: Optional[str] = None,
        generation_id: str = "gen_default",
    ) -> ClaimBindingResult:
        """
        Execute claim-to-evidence binding.
        Invariant: Claim is SUPPORTED iff verified matching EvidenceRecord exists in catalog.
        """
        bindings: List[ClaimEvidenceBinding] = []
        violations: List[CodeViolation] = []
        findings: List[GroundingFinding] = []

        unsupported_bindings: List[ClaimEvidenceBinding] = []
        unknown_bindings: List[ClaimEvidenceBinding] = []

        if not claims:
            return ClaimBindingResult(
                bindings=[],
                grounded_claim_rate=1.0,
                citation_accuracy=1.0,
                grounding_manifest={
                    "generation_id": generation_id,
                    "target_entrypoint": target_entrypoint,
                    "evidence_ids": [],
                    "claims": [],
                },
            )

        used_evidence_set: set[str] = set()

        for claim in claims:
            # 1. Match claim against catalog
            match: Optional[Any] = None
            if hasattr(catalog, "find_match"):
                if isinstance(catalog, EvidenceCatalog2):
                    match = catalog.find_match(claim.kind, claim.value)
                else:
                    match = catalog.find_match(claim)

            if match:
                ev_id = getattr(match, "evidence_id", "EV-UNKNOWN")
                src_path = getattr(match, "source_path", getattr(match, "source", "unknown"))
                chunk_id = getattr(match, "source_chunk_id", "CHK-UNKNOWN")
                commit_sha = getattr(match, "commit_sha", "")

                used_evidence_set.add(ev_id)
                claim.status = "SUPPORTED"
                claim.matched_evidence_id = ev_id

                binding = ClaimEvidenceBinding(
                    claim_id=claim.claim_id,
                    kind=claim.kind,
                    value=claim.value,
                    status="SUPPORTED",
                    evidence_ids=[ev_id],
                    citation_valid=True,
                    source_file=claim.file_path,
                    line_number=claim.line_number,
                    message=f"Supported by verified evidence from '{src_path}'",
                    provenance_chain={
                        "evidence_id": ev_id,
                        "source_chunk_id": chunk_id,
                        "source_path": src_path,
                        "commit_sha": commit_sha,
                    },
                )
                bindings.append(binding)
                findings.append(
                    GroundingFinding(
                        claim_type=claim.kind,
                        claim_value=claim.value,
                        status="SUPPORTED",
                        evidence_id=ev_id,
                        message=binding.message,
                        source_file=claim.file_path,
                    )
                )
            else:
                # 2. Check if domain knowledge exists
                domain_exists = False
                if hasattr(catalog, "has_domain"):
                    domain_exists = catalog.has_domain(claim.kind)

                if domain_exists:
                    # Domain is verified but this claim does NOT exist -> UNSUPPORTED (Hallucination)
                    claim.status = "UNSUPPORTED"
                    v_code, msg, sugg = cls._build_violation(claim, catalog)
                    v = CodeViolation(
                        code=v_code,
                        file_path=claim.file_path,
                        line_number=claim.line_number,
                        message=msg,
                        severity="error",
                        suggestion=sugg,
                    )
                    violations.append(v)
                    binding = ClaimEvidenceBinding(
                        claim_id=claim.claim_id,
                        kind=claim.kind,
                        value=claim.value,
                        status="UNSUPPORTED",
                        evidence_ids=[],
                        citation_valid=False,
                        source_file=claim.file_path,
                        line_number=claim.line_number,
                        message=msg,
                    )
                    bindings.append(binding)
                    unsupported_bindings.append(binding)
                    findings.append(
                        GroundingFinding(
                            claim_type=claim.kind,
                            claim_value=claim.value,
                            status="UNSUPPORTED",
                            evidence_id=None,
                            message=msg,
                            source_file=claim.file_path,
                        )
                    )
                else:
                    # Domain not indexed -> UNKNOWN
                    claim.status = "UNKNOWN"
                    msg = f"Evidence not indexed for {claim.kind} domain. Claim '{claim.value}' cannot be deterministically verified."
                    binding = ClaimEvidenceBinding(
                        claim_id=claim.claim_id,
                        kind=claim.kind,
                        value=claim.value,
                        status="UNKNOWN",
                        evidence_ids=[],
                        citation_valid=True,
                        source_file=claim.file_path,
                        line_number=claim.line_number,
                        message=msg,
                    )
                    bindings.append(binding)
                    unknown_bindings.append(binding)
                    findings.append(
                        GroundingFinding(
                            claim_type=claim.kind,
                            claim_value=claim.value,
                            status="UNKNOWN",
                            evidence_id=None,
                            message=msg,
                            source_file=claim.file_path,
                        )
                    )

        # 3. Citation validation
        citation_accuracy = 1.0
        if claimed_citations:
            valid_citations = 0
            for cid in claimed_citations:
                # Must exist in catalog and match at least one claim
                in_catalog = False
                if hasattr(catalog, "get_by_id"):
                    in_catalog = bool(catalog.get_by_id(cid))
                elif hasattr(catalog, "get_items"):
                    in_catalog = any(item.evidence_id == cid for item in catalog.get_items())

                if in_catalog and cid in used_evidence_set:
                    valid_citations += 1
            citation_accuracy = round(valid_citations / len(claimed_citations), 4)

        # 4. Rates & Summary
        supported_count = sum(1 for b in bindings if b.status == "SUPPORTED")
        grounded_rate = round(supported_count / len(bindings), 4)
        has_blocking = len(violations) > 0

        # 5. Build grounding manifest
        manifest = {
            "generation_id": generation_id,
            "target_entrypoint": target_entrypoint,
            "evidence_ids": list(used_evidence_set),
            "claims": [
                {
                    "claim_id": b.claim_id,
                    "kind": b.kind,
                    "value": b.value,
                    "status": b.status,
                    "evidence_ids": b.evidence_ids,
                    "provenance": b.provenance_chain,
                }
                for b in bindings
            ],
            "grounded_claim_rate": grounded_rate,
            "citation_accuracy": citation_accuracy,
        }

        return ClaimBindingResult(
            bindings=bindings,
            grounded_claim_rate=grounded_rate,
            citation_accuracy=citation_accuracy,
            unsupported_claims=unsupported_bindings,
            unknown_claims=unknown_bindings,
            has_blocking_violations=has_blocking,
            violations=violations,
            findings=findings,
            grounding_manifest=manifest,
        )

    @staticmethod
    def _build_violation(claim: ClaimItem, catalog: Any) -> tuple[CodeViolationCode, str, Optional[str]]:
        """Map unsupported claim to precise CodeViolationCode and suggestion."""
        if claim.kind == "api_endpoint":
            return (
                CodeViolationCode.UNSUPPORTED_API_ENDPOINT,
                f"Generated test calls unverified API endpoint '{claim.value}'.",
                "Verify API endpoint against OpenAPI specifications or route definitions.",
            )
        elif claim.kind == "ui_selector":
            return (
                CodeViolationCode.UNSUPPORTED_UI_SELECTOR,
                f"Generated test uses unverified UI selector '{claim.value}'.",
                "Verify UI locator against DOM or page contract.",
            )
        else:
            return (
                CodeViolationCode.HALLUCINATED_SYMBOL,
                f"Generated test accesses unverified symbol or field '{claim.value}'.",
                "Verify symbol against source AST export list.",
            )
