"""Optional structured-output callbacks for a LangChain chat model."""

from __future__ import annotations

import inspect
from typing import Any

from pydantic import BaseModel, Field

from .state import AgentState


class AgentPlan(BaseModel):
    goal: str
    steps: list[str] = Field(min_length=1, max_length=8)
    test_strategy: str = ""


class AgentReview(BaseModel):
    status: str = Field(pattern="^(pass|fail|uncertain)$")
    issues: list[dict[str, Any]] = Field(default_factory=list)
    rationale: str = ""


class StructuredLLMCallbacks:
    """Turn a LangChain model into bounded Planner and Reviewer callbacks."""

    def __init__(self, model: Any) -> None:
        if not hasattr(model, "with_structured_output"):
            raise TypeError("model must provide with_structured_output()")
        self.plan_model = model.with_structured_output(AgentPlan)
        self.review_model = model.with_structured_output(AgentReview)

    async def planner(self, state: AgentState) -> dict[str, Any]:
        prompt = (
            "Create a minimal test execution plan. Do not invent endpoints or tools.\n"
            f"Requirement: {state.get('requirement', '')}\n"
            f"Framework: {state.get('framework', 'pytest')}\n"
            "Return only the requested structured object."
        )
        result = self.plan_model.invoke(prompt)
        if inspect.isawaitable(result):
            result = await result
        return result.model_dump() if isinstance(result, BaseModel) else dict(result)

    async def reviewer(self, state: AgentState) -> dict[str, Any]:
        execution = state.get("execution_result", {})
        prompt = (
            "Review this generated test run using only the evidence below. "
            "Mark pass only when the test command actually exited successfully.\n"
            f"Execution: {execution}\n"
            f"Repair round: {state.get('repair_round', 0)}\n"
            "Return only the requested structured object."
        )
        result = self.review_model.invoke(prompt)
        if inspect.isawaitable(result):
            result = await result
        return result.model_dump() if isinstance(result, BaseModel) else dict(result)
