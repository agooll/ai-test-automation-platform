"""Unit tests for Evidence-Aware Semantic Code Reviewer."""

import pytest
from unittest.mock import AsyncMock, MagicMock

pytestmark = [pytest.mark.unit]

from testteller.quality_gate.code_reviewer import EvidenceAwareCodeReviewer


@pytest.mark.asyncio
async def test_reviewer_fails_when_execution_failed():
    reviewer = EvidenceAwareCodeReviewer()
    state = {
        "execution_result": {"passed": False, "exit_code": 1, "stderr": "AssertionError"},
        "code_quality_result": {"status": "PASS"},
    }
    result = await reviewer.review(state)
    assert result["status"] == "fail"
    assert result["issues"][0]["code"] == "EXECUTION_FAILURE"


@pytest.mark.asyncio
async def test_reviewer_fails_when_code_quality_rejected():
    reviewer = EvidenceAwareCodeReviewer()
    state = {
        "execution_result": {"passed": True, "exit_code": 0},
        "code_quality_result": {"status": "REJECTED", "repair_feedback": ["Assert always true"]},
    }
    result = await reviewer.review(state)
    assert result["status"] == "fail"
    assert result["issues"][0]["code"] == "CODE_QUALITY_REJECTED"


@pytest.mark.asyncio
async def test_reviewer_passes_with_valid_llm_response():
    mock_llm = MagicMock()
    mock_llm.generate_text = MagicMock(return_value="""
```json
{
  "status": "pass",
  "confidence": 0.95,
  "issues": [],
  "suggestions": ["Add more boundary checks if possible"]
}
```
""")
    reviewer = EvidenceAwareCodeReviewer(generator=mock_llm, min_confidence=0.65)
    state = {
        "requirement": "Test LRUCache capacity eviction",
        "target_entrypoint": "cachetools.LRUCache",
        "generated_files": {"tests/test_lru.py": "def test_eviction(): ..."},
        "grounding_catalog": [{"evidence_id": "SYM-1", "kind": "target_symbol", "value": "LRUCache"}],
        "code_quality_result": {"status": "PASS", "vacuity_score": 1.0, "grounding_score": 1.0},
        "execution_result": {"passed": True, "exit_code": 0, "stdout": "1 passed"},
    }
    result = await reviewer.review(state)
    assert result["status"] == "pass"
    assert result["confidence"] == 0.95
    assert len(result["suggestions"]) == 1


@pytest.mark.asyncio
async def test_reviewer_downgrades_to_uncertain_on_low_confidence():
    mock_llm = MagicMock()
    mock_llm.generate_text = MagicMock(return_value='{"status": "pass", "confidence": 0.4, "issues": [], "suggestions": []}')
    reviewer = EvidenceAwareCodeReviewer(generator=mock_llm, min_confidence=0.65)
    state = {
        "execution_result": {"passed": True, "exit_code": 0},
        "code_quality_result": {"status": "PASS"},
    }
    result = await reviewer.review(state)
    assert result["status"] == "uncertain"


@pytest.mark.asyncio
async def test_reviewer_fails_closed_on_llm_malformed_json():
    mock_llm = MagicMock()
    mock_llm.generate_text = MagicMock(return_value="Sorry, I cannot review this.")
    reviewer = EvidenceAwareCodeReviewer(generator=mock_llm)
    state = {
        "execution_result": {"passed": True, "exit_code": 0},
        "code_quality_result": {"status": "PASS"},
    }
    result = await reviewer.review(state)
    assert result["status"] == "uncertain"
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_reviewer_without_generator_fails_closed_to_uncertain():
    reviewer = EvidenceAwareCodeReviewer(generator=None)
    state = {
        "execution_result": {"passed": True, "exit_code": 0},
        "code_quality_result": {"status": "PASS"},
    }
    result = await reviewer.review(state)
    assert result["status"] == "uncertain"
