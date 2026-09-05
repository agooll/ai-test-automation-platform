"""CLI entry point for the integrated LangGraph test agent."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Optional

import typer

from .service import AgentRunConfig, execute_agent_run, prepare_agent_run


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
    execution_backend: str = "auto",
) -> dict:
    """Generate, execute and repair automation tests through the agent graph."""
    config = AgentRunConfig(
        input_file=input_file,
        collection_name=collection_name,
        language=language,
        framework=framework,
        workspace=output_dir,
        test_command=test_command,
        max_repair_rounds=max_repair_rounds,
        trace_file=trace_file,
        checkpoint_file=checkpoint_file,
        execution_backend=execution_backend,
    )
    try:
        prepared = asyncio.run(prepare_agent_run(config))
        result = asyncio.run(execute_agent_run(prepared))
    except (FileNotFoundError, ValueError) as e:
        raise typer.BadParameter(str(e))

    print(f"Agent verdict: {result.get('final_verdict', 'UNKNOWN')}")
    print(f"Repair rounds: {result.get('repair_round', 0)}")
    print(f"Trace: {prepared.trace_path}")
    return result

