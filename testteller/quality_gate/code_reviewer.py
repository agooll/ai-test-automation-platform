"""Evidence-Aware Semantic Code Reviewer for Stage 4 Quality Gate.

Evaluates generated test code against requirements, evidence catalog,
claims, deterministic AST findings, and sandbox execution results.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Optional, Protocol

from .code_models import CodeSemanticReview

logger = logging.getLogger(__name__)


class TextGenerator(Protocol):
    async def generate_text_async(self, prompt: str) -> str: ...


CODE_REVIEW_PROMPT = """You are the AI Semantic Code Reviewer in the TestTeller Quality Gate.
Your role is to evaluate whether generated automation test code truthfully and rigorously
verifies the required software behavior.
Deterministic AST gates and real sandbox execution have already completed.

=== 1. TEST REQUIREMENT ===
{requirement}

=== 2. TARGET SYSTEM UNDER TEST (SUT) ===
{target_entrypoint}

=== 3. GENERATED TEST FILES ===
{generated_files}

=== 4. FACTUAL EVIDENCE CATALOG ===
{evidence_catalog}

=== 5. EXTRACTED CLAIMS & GROUNDING FINDINGS ===
{claims_and_grounding}

=== 6. DETERMINISTIC AST CODE GATE FINDINGS ===
{code_quality_summary}

=== 7. SANDBOX EXECUTION RESULT ===
{execution_summary}

=== REVIEW INSTRUCTIONS ===
Evaluate the following semantic dimensions:
1. Behavioral Alignment: Does the test code exercise and verify the exact business logic requested?
2. Assertion Quality: Are the assertions verifying meaningful post-conditions and invariants, or are they vacuous/weak?
3. SUT Fidelity: Does the test call the real target component/API, or did it bypass execution or define its own dummy helpers?
4. Negative Testing: If error handling was required, does the test verify the specific exception or error payload?
5. Grounding Accuracy: Are URLs, parameters, and symbols consistent with the factual evidence catalog?

=== HARD INVARIANTS ===
- If sandbox execution failed (exit_code != 0 or passed is False), review status MUST NOT be 'pass'.
- If deterministic code quality has error violations or is REJECTED, review status MUST NOT be 'pass'.
- If the test passes execution only by evading the real requirement or testing nothing, review status MUST be 'fail'.
- If there is insufficient context or uncertain evidence, review status MUST be 'uncertain'.
- Only return status 'pass' when execution succeeded AND the test code genuinely verifies the requirement.

Return JSON ONLY with this exact shape:
{{
  "status": "pass" | "fail" | "uncertain",
  "confidence": 0.0 to 1.0,
  "issues": [
    {{
      "code": "SEMANTIC_MISALIGNMENT" | "WEAK_ASSERTION" | "UNGROUNDED_ASSUMPTION" | "EXECUTION_FAILURE" | "OTHER",
      "message": "...",
      "severity": "error" | "warning",
      "suggestion": "..."
    }}
  ],
  "suggestions": ["..."]
}}
"""


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    candidate = fenced.group(1) if fenced else text.strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end != -1:
            candidate = candidate[start : end + 1]
    return json.loads(candidate)


class EvidenceAwareCodeReviewer:
    """Evaluates full execution, AST findings, evidence, and code against requirements."""

    def __init__(
        self,
        generator: Optional[Any] = None,
        min_confidence: float = 0.65,
    ) -> None:
        self.generator = generator
        self.min_confidence = min_confidence

    async def review(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Perform evidence-aware semantic review on the current agent state."""
        execution = state.get("execution_result", {})
        exec_passed = bool(execution.get("passed", False))
        cq_res = state.get("code_quality_result", {})
        cq_status = cq_res.get("status", "PASS")

        # Fast invariant fail-closed check: if execution or code quality failed
        if not exec_passed:
            return CodeSemanticReview(
                status="fail",
                confidence=1.0,
                issues=[
                    {
                        "code": "EXECUTION_FAILURE",
                        "message": f"Execution did not pass (exit code {execution.get('exit_code')}).",
                        "severity": "error",
                        "suggestion": "Fix runtime errors before requesting semantic pass.",
                    }
                ],
                suggestions=["Resolve test execution failures."],
            ).model_dump(mode="json")

        if cq_status == "REJECTED":
            return CodeSemanticReview(
                status="fail",
                confidence=1.0,
                issues=[
                    {
                        "code": "CODE_QUALITY_REJECTED",
                        "message": "Deterministic code quality gate rejected the test files.",
                        "severity": "error",
                        "suggestion": "Resolve AST and anti-counterfeiting violations.",
                    }
                ],
                suggestions=cq_res.get("repair_feedback", []),
            ).model_dump(mode="json")

        # If no generator available, fail-closed to uncertain
        if not self.generator:
            return CodeSemanticReview(
                status="uncertain",
                confidence=0.0,
                issues=[],
                suggestions=["No LLM text generator available for semantic review."],
            ).model_dump(mode="json")

        prompt = self._build_prompt(state)

        try:
            gen_async = getattr(self.generator, "generate_text_async", None)
            gen_sync = getattr(self.generator, "generate_text", None)

            try:
                from unittest.mock import AsyncMock
            except ImportError:
                AsyncMock = None

            is_real_async = callable(gen_async) and (
                inspect.iscoroutinefunction(gen_async)
                or (AsyncMock is not None and isinstance(gen_async, AsyncMock))
            )

            if is_real_async:
                res = gen_async(prompt)
                raw = await res if inspect.isawaitable(res) else str(res)
            elif callable(gen_sync):
                res = gen_sync(prompt)
                raw = await res if inspect.isawaitable(res) else str(res)
            elif callable(self.generator):
                res = self.generator(prompt)
                raw = await res if inspect.isawaitable(res) else str(res)
            else:
                raw = "{}"

            data = _extract_json(raw)
            result = CodeSemanticReview.model_validate(data)

            # Enforce confidence threshold
            if result.confidence < self.min_confidence and result.status == "pass":
                result.status = "uncertain"

            return result.model_dump(mode="json")

        except Exception as err:
            logger.warning("EvidenceAwareCodeReviewer error: %s", err)
            return CodeSemanticReview(
                status="uncertain",
                confidence=0.0,
                issues=[
                    {
                        "code": "REVIEW_EXCEPTION",
                        "message": f"Semantic review encountered an error: {str(err)}",
                        "severity": "warning",
                        "suggestion": "Check LLM service connectivity and response format.",
                    }
                ],
                suggestions=["AI semantic review did not produce a parseable verdict."],
            ).model_dump(mode="json")

    def _build_prompt(self, state: Dict[str, Any]) -> str:
        req = state.get("requirement", "No requirement provided.")
        target = state.get("target_entrypoint", "None specified.")
        files = state.get("generated_files", {})
        files_str = "\n\n".join(
            f"--- File: {name} ---\n{content}"
            for name, content in files.items()
        ) or "No files."

        catalog = state.get("grounding_catalog", [])
        catalog_str = json.dumps(catalog, indent=2, ensure_ascii=False) if catalog else "No catalog items."

        cq_res = state.get("code_quality_result", {})
        findings = cq_res.get("grounding_findings", [])
        claims_str = json.dumps(findings, indent=2, ensure_ascii=False) if findings else "No claim findings."

        cq_summary = {
            "status": cq_res.get("status"),
            "vacuity_score": cq_res.get("vacuity_score"),
            "grounding_score": cq_res.get("grounding_score"),
            "violations_count": len(cq_res.get("hard_violations", [])),
            "repair_feedback": cq_res.get("repair_feedback", []),
        }
        cq_summary_str = json.dumps(cq_summary, indent=2, ensure_ascii=False)

        exec_res = state.get("execution_result", {})
        exec_summary = {
            "passed": exec_res.get("passed"),
            "exit_code": exec_res.get("exit_code"),
            "duration_ms": exec_res.get("duration_ms"),
            "stdout_tail": (exec_res.get("stdout") or "")[-1500:],
            "stderr_tail": (exec_res.get("stderr") or "")[-1500:],
        }
        exec_summary_str = json.dumps(exec_summary, indent=2, ensure_ascii=False)

        return CODE_REVIEW_PROMPT.format(
            requirement=req,
            target_entrypoint=target,
            generated_files=files_str,
            evidence_catalog=catalog_str,
            claims_and_grounding=claims_str,
            code_quality_summary=cq_summary_str,
            execution_summary=exec_summary_str,
        )
