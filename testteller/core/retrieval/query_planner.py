"""Grounding Query Planner decomposing test requirements into verifiable factual queries (Stage 5.4)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GroundingQuery:
    """A focused sub-query targeting a specific aspect of the codebase or specification."""
    query_id: str
    kind: str  # "target_symbol" | "api_endpoint" | "model_field" | "auth_pattern" | "behavior_contract" | "config"
    text: str
    required: bool = True
    exact_terms: List[str] = field(default_factory=list)
    max_results: int = 5


@dataclass
class GroundingQueryPlan:
    """A complete plan of sub-queries for grounding a test generation or repair run."""
    plan_id: str
    queries: List[GroundingQuery]
    requirement_text: str
    target_entrypoint: Optional[str] = None


class GroundingQueryPlanner:
    """Decomposes requirements into structured factual query plans without hallucinating assumptions."""

    HTTP_ENDPOINT_PATTERN = re.compile(
        r"\b(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s+([/\w\-\{\}\.]+)", re.IGNORECASE
    )
    PATH_PATTERN = re.compile(r"(/[a-zA-Z0-9_\-\{\}/]+)")
    CAMEL_CASE_PATTERN = re.compile(r"\b[A-Z][a-zA-Z0-9]+(?:Service|Controller|Handler|Model|Client|Manager|Cache|Repo)\b")
    STATUS_CODE_PATTERN = re.compile(r"\b(200|201|204|400|401|403|404|409|422|500)\b")
    AUTH_KEYWORDS = {"auth", "bearer", "token", "jwt", "login", "authenticate", "unauthorized", "credential", "permission"}
    CONFIG_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")

    def plan(
        self,
        requirement_text: str,
        target_entrypoint: Optional[str] = None,
    ) -> GroundingQueryPlan:
        """Deconstruct requirement into deterministic queries."""
        plan_hash = hashlib.sha256(f"{target_entrypoint}:{requirement_text}".encode("utf-8")).hexdigest()[:12]
        plan_id = f"GQP-{plan_hash}"
        queries: List[GroundingQuery] = []
        counter = 0

        # 1. Target Symbol
        if target_entrypoint:
            counter += 1
            short_name = target_entrypoint.split(".")[-1]
            queries.append(
                GroundingQuery(
                    query_id=f"Q-{counter:02d}",
                    kind="target_symbol",
                    text=f"Target entrypoint symbol {target_entrypoint}",
                    required=True,
                    exact_terms=[target_entrypoint, short_name],
                )
            )

        # Extract other CamelCase classes
        classes = self.CAMEL_CASE_PATTERN.findall(requirement_text)
        for cls_name in dict.fromkeys(classes):
            if not target_entrypoint or cls_name not in target_entrypoint:
                counter += 1
                queries.append(
                    GroundingQuery(
                        query_id=f"Q-{counter:02d}",
                        kind="target_symbol",
                        text=f"Class or service {cls_name}",
                        required=False,
                        exact_terms=[cls_name],
                    )
                )

        # 2. API Endpoints
        endpoint_matches = self.HTTP_ENDPOINT_PATTERN.findall(requirement_text)
        for method, path in endpoint_matches:
            counter += 1
            norm_endpoint = f"{method.upper()} {path.strip()}"
            queries.append(
                GroundingQuery(
                    query_id=f"Q-{counter:02d}",
                    kind="api_endpoint",
                    text=norm_endpoint,
                    required=True,
                    exact_terms=[norm_endpoint, path.strip()],
                )
            )

        # If no method matched, check for paths like /api/...
        if not endpoint_matches:
            paths = [p for p in self.PATH_PATTERN.findall(requirement_text) if len(p) > 2 and "/" in p[1:]]
            for p in dict.fromkeys(paths):
                counter += 1
                queries.append(
                    GroundingQuery(
                        query_id=f"Q-{counter:02d}",
                        kind="api_endpoint",
                        text=f"Endpoint path {p}",
                        required=True,
                        exact_terms=[p],
                    )
                )

        # 3. Model / Request Fields
        field_candidates = self._extract_field_candidates(requirement_text)
        if field_candidates:
            counter += 1
            queries.append(
                GroundingQuery(
                    query_id=f"Q-{counter:02d}",
                    kind="model_field",
                    text=f"Schema fields: {', '.join(field_candidates)}",
                    required=False,
                    exact_terms=field_candidates,
                )
            )

        # 4. Auth Requirements
        req_lower = requirement_text.lower()
        if any(kw in req_lower for kw in self.AUTH_KEYWORDS):
            counter += 1
            queries.append(
                GroundingQuery(
                    query_id=f"Q-{counter:02d}",
                    kind="auth_pattern",
                    text="Authentication, security scheme, or authorization requirement",
                    required=False,
                    exact_terms=["bearer", "auth", "token"],
                )
            )

        # 5. Behavioral Contract / Expected Responses
        status_codes = self.STATUS_CODE_PATTERN.findall(requirement_text)
        if status_codes:
            counter += 1
            queries.append(
                GroundingQuery(
                    query_id=f"Q-{counter:02d}",
                    kind="behavior_contract",
                    text=f"Response status codes: {', '.join(dict.fromkeys(status_codes))}",
                    required=False,
                    exact_terms=list(dict.fromkeys(status_codes)),
                )
            )

        # 6. Config / Env Keys
        configs = [c for c in self.CONFIG_PATTERN.findall(requirement_text) if c not in {"GET", "POST", "PUT", "DELETE", "HTTP"}]
        if configs:
            counter += 1
            queries.append(
                GroundingQuery(
                    query_id=f"Q-{counter:02d}",
                    kind="config",
                    text=f"Environment or configuration variables: {', '.join(dict.fromkeys(configs))}",
                    required=False,
                    exact_terms=list(dict.fromkeys(configs)),
                )
            )

        return GroundingQueryPlan(
            plan_id=plan_id,
            queries=queries,
            requirement_text=requirement_text,
            target_entrypoint=target_entrypoint,
        )

    def _extract_field_candidates(self, text: str) -> List[str]:
        """Look for common field/param names in requirement text."""
        candidates = []
        for word in re.findall(r"\b[a-z_][a-z0-9_]{2,}\b", text):
            if word in {
                "email", "username", "password", "user_id", "id", "name", "token",
                "status", "title", "description", "quantity", "amount", "phone",
            }:
                candidates.append(word)
        return list(dict.fromkeys(candidates))
