"""Typed state shared by the LangGraph test-agent workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    task_id: str
    requirement: str
    language: str
    framework: str
    workspace: str
    test_command: list[str]
    test_plan: dict[str, Any]
    retrieved_context: list[dict[str, Any]]
    generated_files: dict[str, str]
    generation_success: bool
    execution_result: dict[str, Any]
    first_execution_result: dict[str, Any]
    execution_success: bool
    repair_success: bool
    failure_analysis: dict[str, Any]
    repair_round: int
    max_repair_rounds: int
    final_verdict: str
    review: dict[str, Any]
    human_review: bool
    human_decision: str
    repair_history: list[dict[str, Any]]
    execution_backend: str
    trace: list[dict[str, Any]]
    trace_path: str
    error: str | None

    # Stage 4 Quality Gate & Grounding
    target_entrypoint: str | None
    code_quality_result: dict[str, Any]
    code_quality_history: list[dict[str, Any]]
    vacuity_score: float
    grounding_score: float
    grounding_catalog: list[dict[str, Any]]
    unsupported_claims: list[dict[str, Any]]
    semantic_quality_result: dict[str, Any]
    previous_generated_files: dict[str, str]
    weakening_detected: bool
