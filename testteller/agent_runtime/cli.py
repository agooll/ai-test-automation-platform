"""CLI entry point for the integrated LangGraph test agent."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Optional

import typer

from ..automator_agent.cli import get_collection_name, get_framework, get_language, initialize_vector_store
from ..automator_agent.parser.markdown_parser import MarkdownTestCaseParser
from ..automator_agent.rag_enhanced_generator import RAGEnhancedTestGenerator
from ..core.data_ingestion.unified_document_parser import UnifiedDocumentParser
from ..core.llm.llm_manager import LLMManager
from ..quality_gate.gate import QualityGate
from ..quality_gate.reviewer import AIReviewSkill
from .adapters import build_existing_rag_workflow


def agent_run_command(
    input_file: str,
    collection_name: Optional[str] = None,
    language: Optional[str] = None,
    framework: Optional[str] = None,
    output_dir: str = "./testteller_agent_runs",
    test_command: str = "python -m pytest -q",
    max_repair_rounds: int = 2,
    trace_file: Optional[str] = None,
    checkpoint_file: Optional[str] = None,
) -> dict:
    """Generate, execute and repair automation tests through the agent graph."""
    input_path = Path(input_file)
    if not input_path.is_file():
        raise typer.BadParameter(f"Input file not found: {input_file}")
    if max_repair_rounds < 0 or max_repair_rounds > 3:
        raise typer.BadParameter("max_repair_rounds must be between 0 and 3")

    language = get_language(language)
    framework = get_framework(framework, language)
    collection_name = get_collection_name(collection_name)
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    trace_path = Path(trace_file).resolve() if trace_file else output_path / "agent_trace.jsonl"

    llm_manager = LLMManager()
    vector_store = initialize_vector_store(collection_name)
    parsed_doc = asyncio.run(UnifiedDocumentParser().parse_for_automation(input_path))
    test_cases = parsed_doc.test_cases
    if not test_cases and input_path.suffix.lower() == ".md":
        test_cases = MarkdownTestCaseParser().parse_file(input_path)
    if not test_cases:
        raise typer.BadParameter("No structured test cases found in input file")

    quality = asyncio.run(QualityGate(AIReviewSkill(llm_manager)).evaluate_cases(test_cases, use_ai=True))
    if quality.status != "PASS":
        raise typer.BadParameter(f"Quality gate blocked agent run: {quality.status}")

    generator = RAGEnhancedTestGenerator(
        framework=framework, output_dir=output_path, vector_store=vector_store,
        language=language, llm_manager=llm_manager,
    )
    workflow = build_existing_rag_workflow(
        generator, test_cases, llm_manager, checkpoint_path=checkpoint_file
    )
    try:
        command = shlex.split(test_command, posix=False)
        result = asyncio.run(workflow.run({
            "requirement": f"Automate test cases from {input_path.name}",
            "language": language,
            "framework": framework,
            "workspace": str(output_path),
            "test_command": command,
            "max_repair_rounds": max_repair_rounds,
            "trace_path": str(trace_path),
        }))
    finally:
        asyncio.run(workflow.aclose())
        vector_store.close()

    print(f"Agent verdict: {result.get('final_verdict', 'UNKNOWN')}")
    print(f"Repair rounds: {result.get('repair_round', 0)}")
    print(f"Trace: {trace_path}")
    return result
