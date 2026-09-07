"""Structured Repair Planner and Evidence-Grounded Repair Invariant (Stage 5.6)."""

from __future__ import annotations

import ast
import logging
import re
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from testteller.core.evidence.catalog import EvidenceCatalog2
from testteller.core.evidence.models import EvidenceRecord, TrustLevel
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


class ASTExpectationExtractor:
    """
    Extracts deterministic expectation fingerprints from test AST without brittle regexes.
    Detects modifications to status codes, return values, exception types, and assertions.
    """

    @classmethod
    def extract_expectations(cls, code: str) -> dict[str, set[str]]:
        """
        Extract normalized (target -> set of expected values) from Python test AST.
        """
        try:
            tree = ast.parse(code)
        except Exception:
            return {}

        expectations: dict[str, set[str]] = {}

        def add_exp(target: str, val: str):
            t = target.strip()
            v = val.strip().strip("\"'")
            if t and v:
                expectations.setdefault(t, set()).add(v)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                test = node.test
                if isinstance(test, ast.Compare):
                    left_norm = cls._normalize_expr(test.left)
                    for op, comp in zip(test.ops, test.comparators):
                        if isinstance(op, ast.Eq):
                            comp_str = ast.unparse(comp) if hasattr(ast, "unparse") else ""
                            add_exp(left_norm, comp_str)
                elif isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
                    operand_str = cls._normalize_expr(test.operand)
                    add_exp(operand_str, "False")
                elif isinstance(test, (ast.Call, ast.Name, ast.Attribute)):
                    expr_str = cls._normalize_expr(test)
                    add_exp(expr_str, "True")

            elif isinstance(node, ast.With):
                for item in node.items:
                    expr = item.context_expr
                    if isinstance(expr, ast.Call):
                        func_str = ast.unparse(expr.func) if hasattr(ast, "unparse") else ""
                        if "pytest.raises" in func_str and expr.args:
                            arg_str = ast.unparse(expr.args[0]) if hasattr(ast, "unparse") else ""
                            add_exp("pytest.raises", arg_str)

            elif isinstance(node, ast.Call):
                func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if func_str.endswith(".assertEqual") and len(node.args) >= 2:
                    left_str = cls._normalize_expr(node.args[0])
                    right_str = ast.unparse(node.args[1]) if hasattr(ast, "unparse") else ""
                    add_exp(left_str, right_str)
                elif func_str.endswith(".assertRaises") and len(node.args) >= 1:
                    exc_str = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else ""
                    add_exp("pytest.raises", exc_str)

        return expectations

    @classmethod
    def _normalize_expr(cls, node: ast.AST) -> str:
        if isinstance(node, ast.Attribute):
            if node.attr in ("status_code", "status"):
                return "status_code"
            return f"*.{node.attr}"
        if isinstance(node, ast.Subscript):
            slice_str = ast.unparse(node.slice) if hasattr(ast, "unparse") else ""
            return f"*[{slice_str}]"
        return ast.unparse(node) if hasattr(ast, "unparse") else ""

    @classmethod
    def find_unbacked_expectation_changes(
        cls,
        before_code: str,
        proposed_code: str,
        catalog_records: list[EvidenceRecord],
    ) -> list[str]:
        """
        Compare before_code and proposed_code AST expectation fingerprints.
        Any modified or newly altered expectation that lacks authoritative evidence
        is returned as an unbacked violation.
        """
        before_exp = cls.extract_expectations(before_code)
        after_exp = cls.extract_expectations(proposed_code)

        unbacked: list[str] = []

        for target, after_vals in after_exp.items():
            before_vals = before_exp.get(target, set())
            new_vals = after_vals - before_vals
            if new_vals and before_vals:
                for val in new_vals:
                    has_auth = False
                    for ev in catalog_records:
                        trust = getattr(ev, "trust_level", None)
                        is_auth = (
                            trust in (TrustLevel.T0_AUTHORITATIVE, TrustLevel.T1_STRONG)
                            or getattr(trust, "is_authoritative", False)
                        )
                        if is_auth:
                            ev_val = str(getattr(ev, "value", ""))
                            meta_str = str(getattr(ev, "metadata", {}))
                            if target == "status_code":
                                if (
                                    f"status_code {val}" in ev_val
                                    or f"-> {val}" in ev_val
                                    or ev_val.endswith(f" {val}")
                                    or f"'{val}'" in meta_str
                                    or f": {val}" in meta_str
                                ):
                                    has_auth = True
                                    break
                            else:
                                if val in ev_val or val in meta_str:
                                    has_auth = True
                                    break
                    if not has_auth:
                        unbacked.append(f"Expectation for '{target}' modified to '{val}' without authoritative evidence")

        return unbacked

