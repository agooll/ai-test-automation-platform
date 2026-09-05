"""Structured AI semantic reviewer used after deterministic validation."""

import json
import logging
import re
from typing import Protocol

from .models import NormalizedTestCase, SemanticReviewResult, TestCaseCollection

logger = logging.getLogger(__name__)


class TextGenerator(Protocol):
    async def generate_text_async(self, prompt: str) -> str: ...


REVIEW_PROMPT = """You are the semantic reviewer in a software test-case quality gate.
Review the supplied normalized test cases. Deterministic schema and rule validation has already run.
Do not invent missing facts. Check only semantic quality: clarity, automation feasibility,
verifiable expected results, hidden prerequisites, requirement alignment, realistic data,
and invented APIs/pages/fields.

Return JSON only with this exact shape:
{{"status":"pass|fail|uncertain","confidence":0.0,"issues":[{{"code":"...","message":"...","severity":"error|warning","field":"..."}}],"suggestions":[],"evidence":[]}}

Test cases:
{payload}
"""


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    candidate = fenced.group(1) if fenced else text.strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        candidate = candidate[start:end + 1]
    return json.loads(candidate)


class AIReviewSkill:
    def __init__(self, generator: TextGenerator, min_confidence: float = 0.65):
        self.generator = generator
        self.min_confidence = min_confidence

    async def review(self, collection: TestCaseCollection) -> SemanticReviewResult:
        payload = collection.model_dump_json(indent=2)
        try:
            raw = await self.generator.generate_text_async(REVIEW_PROMPT.format(payload=payload))
            result = SemanticReviewResult.model_validate(_extract_json(raw))
            if result.confidence < self.min_confidence and result.status == "pass":
                result.status = "uncertain"
            return result
        except Exception as error:
            logger.warning("AI semantic review unavailable: %s", error)
            return SemanticReviewResult(
                status="uncertain",
                confidence=0.0,
                issues=[],
                suggestions=["AI semantic review did not produce a valid result"],
                evidence=[],
            )

