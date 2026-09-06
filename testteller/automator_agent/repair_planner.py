"""Structured Repair Planner and Evidence-Grounded Repair Invariant (Stage 5.6)."""

from __future__ import annotations

import logging
import re
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from testteller.core.evidence.catalog import EvidenceCatalog2
from testteller.core.retrieval.query_planner import GroundingQuery

logger = logging.getLogger(__name__)


class RepairChange(BaseModel):
    """An individual proposed change in a repair plan."""
    model_config = ConfigDict(extra="ignore")

    change_type: Literal["fix_syntax", "fix_import", "fix_sut_call", "alter_expectation"]
    target: str
    description: str
    evidence_id: Optional[str] = None


class RepairPlan(BaseModel):
    """Structured repair plan enforcing evidence backing for expectation changes."""
    model_config = ConfigDict(extra="ignore")

    root_cause: str
    proposed_changes: List[RepairChange] = Field(default_factory=list)
    required_evidence_ids: List[str] = Field(default_factory=list)
    expectation_changes: List[str] = Field(default_factory=list)
    allow_repair: bool = True
    rejection_reason: Optional[str] = None


class RepairGroundingPlanner:
    """Analyzes execution failures and formulates targeted grounding queries and repair plans."""

    ATTR_ERROR_PATTERN = re.compile(r"AttributeError:\s*'?(\w+)'?\s*object has no attribute\s*'(\w+)'")
    HTTP_404_PATTERN = re.compile(r"404\s+(?:Not Found|Client Error):\s*(?:for url:)?\s*([^\s\n]+)")
    HTTP_405_PATTERN = re.compile(r"405\s+(?:Method Not Allowed):\s*(?:for url:)?\s*([^\s\n]+)")

    @classmethod
    def formulate_repair_queries(cls, failure_evidence: str) -> List[GroundingQuery]:
        """Formulate targeted retrieval queries based on failure logs."""
        queries: List[GroundingQuery] = []
        counter = 0

        # Check for AttributeError (wrong method or property name)
        for obj_name, attr_name in cls.ATTR_ERROR_PATTERN.findall(failure_evidence):
            counter += 1
            queries.append(
                GroundingQuery(
                    query_id=f"RQ-{counter:02d}",
                    kind="target_symbol",
                    text=f"Methods and attributes of {obj_name}",
                    required=True,
                    exact_terms=[obj_name, attr_name],
                )
            )

        # Check for 404 or 405 endpoint errors
        for url in cls.HTTP_404_PATTERN.findall(failure_evidence) + cls.HTTP_405_PATTERN.findall(failure_evidence):
            counter += 1
            queries.append(
                GroundingQuery(
                    query_id=f"RQ-{counter:02d}",
                    kind="api_endpoint",
                    text=f"Valid endpoint for {url}",
                    required=True,
                    exact_terms=[url],
                )
            )

        return queries

    @classmethod
    def validate_repair_plan(
        cls,
        plan: RepairPlan,
        catalog: EvidenceCatalog2,
    ) -> RepairPlan:
        """
        Enforce Stage 5 Invariant:
        Any change to test expectation (status code, return value, exception type)
        strictly requires an authoritative, verified evidence_id in catalog.
        """
        for exp_change in plan.expectation_changes:
            # Check if this expectation change has a supporting evidence_id
            supporting_ev = None
            for ev_id in plan.required_evidence_ids:
                record = catalog.get_by_id(ev_id)
                if record and record.trust_level.is_authoritative:
                    supporting_ev = record
                    break

            if not supporting_ev:
                plan.allow_repair = False
                plan.rejection_reason = (
                    f"Rejected expectation change '{exp_change}': No authoritative evidence_id provided. "
                    "Tests must not alter business expectations without canonical evidence."
                )
                logger.warning("Repair plan rejected: %s", plan.rejection_reason)
                return plan

        return plan
