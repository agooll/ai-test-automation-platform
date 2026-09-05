"""Application service layer for Agent Run execution, shared by CLI and Web."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shlex
import sys
import uuid
from typing import Any, Awaitable, Callable, Optional

from ..automator_agent.cli import get_collection_name, get_framework, get_language, initialize_vector_store
from ..automator_agent.parser.markdown_parser import MarkdownTestCaseParser, TestCase
from ..automator_agent.rag_enhanced_generator import RAGEnhancedTestGenerator
from ..core.data_ingestion.unified_document_parser import UnifiedDocumentParser
from ..core.llm.llm_manager import LLMManager
from ..quality_gate.gate import QualityGate
from ..quality_gate.reviewer import AIReviewSkill
from .adapters import build_existing_rag_workflow
from .graph import AgenticTestWorkflow
from .state import AgentState

EventSink = Callable[[dict[str, Any]], None | Awaitable[None]]


@dataclass
class AgentRunConfig:
    input_file: str
    collection_name: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None
    workspace: Optional[str] = None
    test_command: Optional[str] = None
    max_repair_rounds: int = 2
    human_review: bool = False
    trace_file: Optional[str] = None
    checkpoint_file: Optional[str] = None
    task_id: Optional[str] = None
    event_sink: Optional[EventSink] = None


@dataclass
class PreparedAgentRun:
    task_id: str
    workspace: Path
    trace_path: Path
    language: str
    framework: str
    test_command: list[str]
    test_cases: list[TestCase]
    llm_manager: LLMManager
    vector_store: Any
    workflow: AgenticTestWorkflow
    initial_state: AgentState


async def prepare_agent_run(config: AgentRunConfig) -> PreparedAgentRun:
    input_path = Path(config.input_file).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {config.input_file}")
    if config.max_repair_rounds < 0 or config.max_repair_rounds > 3:
        raise ValueError("max_repair_rounds must be between 0 and 3")

    task_id = config.task_id or str(uuid.uuid4())
    language = get_language(config.language)
    framework = get_framework(config.framework, language)
    collection_name = get_collection_name(config.collection_name)

    if config.workspace:
        output_path = Path(config.workspace).resolve()
    else:
        output_path = Path("./testteller_agent_runs").resolve() / task_id
    output_path.mkdir(parents=True, exist_ok=True)

    trace_path = Path(config.trace_file).resolve() if config.trace_file else output_path / "agent_trace.jsonl"
    checkpoint_path = config.checkpoint_file or str(output_path / "agent_checkpoint.sqlite")

    raw_command = config.test_command or f"{sys.executable} -m pytest -q"
    parsed_command = shlex.split(raw_command, posix=False)

    llm_manager = LLMManager()
    vector_store = initialize_vector_store(collection_name)

    parsed_doc = await UnifiedDocumentParser().parse_for_automation(input_path)
    test_cases = parsed_doc.test_cases
    if not test_cases and input_path.suffix.lower() == ".md":
        test_cases = MarkdownTestCaseParser().parse_file(input_path)
    if not test_cases:
        vector_store.close()
        raise ValueError("No structured test cases found in input file")

    quality = await QualityGate(AIReviewSkill(llm_manager)).evaluate_cases(test_cases, use_ai=True)
    if quality.status != "PASS":
        vector_store.close()
        raise ValueError(f"Quality gate blocked agent run: {quality.status}")

    generator = RAGEnhancedTestGenerator(
        framework=framework,
        output_dir=output_path,
        vector_store=vector_store,
        language=language,
        llm_manager=llm_manager,
    )
    workflow = build_existing_rag_workflow(
        generator=generator,
        test_cases=test_cases,
        llm_manager=llm_manager,
        checkpoint_path=checkpoint_path,
        event_sink=config.event_sink,
    )

    initial_state: AgentState = {
        "task_id": task_id,
        "requirement": f"Automate test cases from {input_path.name}",
        "language": language,
        "framework": framework,
        "workspace": str(output_path),
        "test_command": parsed_command,
        "max_repair_rounds": config.max_repair_rounds,
        "trace_path": str(trace_path),
        "human_review": config.human_review,
        "repair_history": [],
    }

    return PreparedAgentRun(
        task_id=task_id,
        workspace=output_path,
        trace_path=trace_path,
        language=language,
        framework=framework,
        test_command=parsed_command,
        test_cases=test_cases,
        llm_manager=llm_manager,
        vector_store=vector_store,
        workflow=workflow,
        initial_state=initial_state,
    )


async def execute_agent_run(prepared: PreparedAgentRun) -> AgentState:
    try:
        result = await prepared.workflow.run(prepared.initial_state, thread_id=prepared.task_id)
        return result
    finally:
        await prepared.workflow.aclose()
        prepared.vector_store.close()
