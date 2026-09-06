"""Trust hierarchy and authority policies for evidence validation and conflict resolution."""

from __future__ import annotations

from typing import Optional
from .models import EvidenceRecord, TrustLevel


KIND_AUTHORITY_WEIGHTS = {
    "ast_extractor": 100,
    "openapi_extractor": 95,
    "project_tests": 80,
    "doc_extractor": 50,
    "llm_inference": 10,
}


def can_support_factual_claim(trust_level: TrustLevel | str) -> bool:
    """
    Check if trust level can independently support a factual claim (endpoint, symbol, schema field).
    T0 (Authoritative) and T1 (Strong) can.
    T2 (Supporting), T3 (Weak), and T4 (Unverified) cannot alone support hard factual claims.
    """
    if isinstance(trust_level, str):
        try:
            trust_level = TrustLevel(trust_level)
        except ValueError:
            return False
    return trust_level in (TrustLevel.T0_AUTHORITATIVE, TrustLevel.T1_STRONG)


def resolve_authority_winner(
    ev_a: EvidenceRecord,
    ev_b: EvidenceRecord,
    pinned_commit: Optional[str] = None,
) -> Optional[EvidenceRecord]:
    """
    Resolve precedence between two conflicting evidence records.

    Hierarchy:
    1. Pinned commit precedence: A record from the pinned commit always supersedes a stale commit.
    2. Trust level rank: T0 > T1 > T2 > T3 > T4.
    3. Extractor authority: Source AST > OpenAPI > Tests > Docs.
    4. If unresolved / equal authority: returns None (unresolvable conflict -> NEEDS_REVIEW).
    """
    # 1. Check pinned commit precedence
    if pinned_commit:
        pinned_a = (ev_a.commit_sha == pinned_commit)
        pinned_b = (ev_b.commit_sha == pinned_commit)
        if pinned_a and not pinned_b:
            return ev_a
        elif pinned_b and not pinned_a:
            return ev_b

    # 2. Check TrustLevel rank (lower numeric rank is better)
    rank_a = ev_a.trust_level.rank
    rank_b = ev_b.trust_level.rank
    if rank_a < rank_b:
        return ev_a
    elif rank_b < rank_a:
        return ev_b

    # 3. Check extractor authority weight
    weight_a = KIND_AUTHORITY_WEIGHTS.get(ev_a.extractor, 50)
    weight_b = KIND_AUTHORITY_WEIGHTS.get(ev_b.extractor, 50)
    if weight_a > weight_b:
        return ev_a
    elif weight_b > weight_a:
        return ev_b

    # 4. Check confidence
    if ev_a.confidence > ev_b.confidence:
        return ev_a
    elif ev_b.confidence > ev_a.confidence:
        return ev_b

    # Unresolvable conflict
    return None
