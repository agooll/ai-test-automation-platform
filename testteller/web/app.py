"""FastAPI console for TestTeller RAG test generation and Agent execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Literal, Optional
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from testteller.agent_runtime.graph import AgenticTestWorkflow
from testteller.agent_runtime.service import AgentRunConfig, PreparedAgentRun, prepare_agent_run
from testteller.agent_runtime.state import AgentState
from testteller.generator_agent.agent.testteller_agent import TestTellerAgent

logger = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent
COLLECTION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

app = FastAPI(title="TestTeller Console", version="0.2.0")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


class CollectionRequest(BaseModel):
    collection_name: str = Field("test_collection", min_length=1, max_length=80)


class IngestDocumentsRequest(CollectionRequest):
    path: str = Field(min_length=1)
    chunk_size: int = Field(1000, ge=200, le=5000)


class IngestCodeRequest(CollectionRequest):
    source_path: str = Field(min_length=1)


class GenerateRequest(CollectionRequest):
    query: str = Field(min_length=3, max_length=10000)
    num_retrieved_docs: int = Field(5, ge=1, le=20)


class QualityCheckRequest(BaseModel):
    content: str = Field(min_length=1, max_length=200000)
    use_ai: bool = True


class AgentRunRequest(BaseModel):
    input_file: Optional[str] = None
    markdown_content: Optional[str] = None
    framework: Optional[str] = "pytest"
    test_command: Optional[str] = "python -m pytest -q"
    max_repair_rounds: int = Field(2, ge=0, le=3)
    human_review: bool = True
    collection_name: Optional[str] = "test_collection"
    language: Optional[str] = "python"
    execution_backend: Optional[str] = "auto"



class ResumeRequest(BaseModel):
    decision: Literal["approve", "reject"]


async def _safe_close(target: Any) -> None:
    if target is None:
        return
    for method_name in ("aclose", "close"):
        fn = getattr(target, method_name, None)
        if callable(fn):
            try:
                res = fn()
                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                    await res
                break
            except Exception:
                pass


@dataclass
class AgentJob:
    task_id: str
    status: str  # QUEUED, RUNNING, WAITING_REVIEW, PASS, REJECTED, FAILED, ERROR
    config: AgentRunConfig
    events_history: list[dict[str, Any]] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    workflow: Optional[AgenticTestWorkflow] = None
    vector_store: Any = None
    result: Optional[AgentState] = None
    error: Optional[str] = None

    async def emit(self, event_data: dict[str, Any]) -> None:
        if "timestamp" not in event_data:
            event_data["timestamp"] = time.time()
        self.events_history.append(event_data)
        for q in list(self.subscribers):
            await q.put(event_data)


class AgentJobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, AgentJob] = {}

    def get_job(self, task_id: str) -> Optional[AgentJob]:
        return self.jobs.get(task_id)

    async def create_job(self, req: AgentRunRequest) -> AgentJob:
        task_id = str(uuid.uuid4())
        input_file = req.input_file

        if not input_file or not Path(input_file).is_file():
            if req.markdown_content and req.markdown_content.strip():
                run_dir = Path("./testteller_agent_runs").resolve() / task_id
                run_dir.mkdir(parents=True, exist_ok=True)
                temp_file = run_dir / "test_cases.md"
                temp_file.write_text(req.markdown_content.strip(), encoding="utf-8")
                input_file = str(temp_file)
            else:
                raise HTTPException(400, "Must provide valid input_file path or non-empty markdown_content")

        job: AgentJob | None = None

        async def event_sink(event_data: dict[str, Any]) -> None:
            if job:
                ev_type = event_data.get("event")
                if ev_type == "RUN_STARTED":
                    job.status = "RUNNING"
                elif ev_type == "WAITING_REVIEW":
                    job.status = "WAITING_REVIEW"
                elif ev_type == "RUN_COMPLETED":
                    verdict = event_data.get("final_verdict")
                    if verdict:
                        job.status = verdict
                await job.emit(event_data)

        config = AgentRunConfig(
            input_file=input_file,
            collection_name=req.collection_name,
            language=req.language,
            framework=req.framework,
            test_command=req.test_command,
            max_repair_rounds=req.max_repair_rounds,
            human_review=req.human_review,
            task_id=task_id,
            event_sink=event_sink,
            execution_backend=req.execution_backend or "auto",
        )


        job = AgentJob(task_id=task_id, status="QUEUED", config=config)
        self.jobs[task_id] = job
        asyncio.create_task(self._run_job(job))
        return job

    async def _run_job(self, job: AgentJob) -> None:
        try:
            prepared: PreparedAgentRun = await prepare_agent_run(job.config)
            job.workflow = prepared.workflow
            job.vector_store = prepared.vector_store
            if not job.workflow.event_sink:
                job.workflow.event_sink = job.config.event_sink

            result = await prepared.workflow.run(prepared.initial_state, thread_id=job.task_id)
            job.result = result

            if "__interrupt__" in result:
                job.status = "WAITING_REVIEW"
            else:
                verdict = result.get("final_verdict")
                if not verdict:
                    verdict = "PASS" if result.get("execution_success") else "FAILED"
                job.status = verdict
                await _safe_close(prepared.workflow)
                await _safe_close(prepared.vector_store)
        except Exception as e:
            logger.exception("Agent job execution error: %s", e)
            job.status = "ERROR"
            job.error = str(e)
            await job.emit({"event": "RUN_ERROR", "task_id": job.task_id, "error": str(e)})
            await _safe_close(job.workflow)
            await _safe_close(job.vector_store)

    async def resume_job(self, task_id: str, decision: str) -> dict[str, Any]:
        job = self.jobs.get(task_id)
        if not job:
            raise HTTPException(404, f"Task not found: {task_id}")
        if job.status != "WAITING_REVIEW" or not job.workflow:
            raise HTTPException(400, f"Task is not waiting for review (status: {job.status})")

        job.status = "RUNNING"
        try:
            result = await job.workflow.resume(task_id, decision)
            job.result = result
            verdict = result.get("final_verdict")
            if not verdict:
                verdict = "PASS" if result.get("execution_success") else "FAILED"
            job.status = verdict
            return {"task_id": task_id, "status": job.status, "result": result}
        except Exception as e:
            logger.exception("Error resuming agent job: %s", e)
            job.status = "ERROR"
            job.error = str(e)
            await job.emit({"event": "RUN_ERROR", "task_id": task_id, "error": str(e)})
            raise HTTPException(500, f"Error resuming run: {e}")
        finally:
            await _safe_close(job.workflow)
            await _safe_close(job.vector_store)




job_manager = AgentJobManager()


def _validate_collection(collection_name: str) -> str:
    if not COLLECTION_PATTERN.fullmatch(collection_name):
        raise HTTPException(422, "Collection 名称只能包含字母、数字、下划线和连字符。")
    return collection_name


def _agent(collection_name: str) -> TestTellerAgent:
    return TestTellerAgent(collection_name=_validate_collection(collection_name))


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict:
    provider = os.getenv("LLM_PROVIDER", "gemini")
    key_configured = bool(
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("CLAUDE_API_KEY")
        or os.getenv("OLLAMA_BASE_URL")
    )
    return {
        "status": "ok",
        "provider": provider,
        "api_key_configured": key_configured,
    }


@app.post("/api/status")
async def status(request: CollectionRequest) -> dict:
    try:
        agent = _agent(request.collection_name)
    except Exception as error:
        logger.warning("Could not initialize TestTellerAgent for status: %s", error)
        return {
            "collection_name": request.collection_name,
            "count": 0,
            "provider": os.getenv("LLM_PROVIDER", "gemini"),
            "storage": "local ChromaDB",
            "warning": f"LLM API Key 未配置（请在 .env 中配置，例如 GOOGLE_API_KEY）: {error}",
        }
    try:
        count = await agent.get_ingested_data_count()
        return {
            "collection_name": request.collection_name,
            "count": count,
            "provider": agent.llm_manager.provider,
            "storage": agent.vector_store.db_path if not agent.vector_store.use_remote else "remote ChromaDB",
        }
    except Exception as error:
        logger.warning("Error fetching collection count: %s", error)
        return {
            "collection_name": request.collection_name,
            "count": 0,
            "provider": agent.llm_manager.provider,
            "storage": "local ChromaDB",
            "warning": str(error),
        }
    finally:
        agent.close()



@app.post("/api/ingest-docs")
async def ingest_documents(request: IngestDocumentsRequest) -> dict:
    path = Path(request.path).expanduser()
    if not path.exists():
        raise HTTPException(404, f"找不到路径：{path}")
    agent = _agent(request.collection_name)
    try:
        await agent.ingest_documents_from_path(str(path), enhanced_parsing=True, chunk_size=request.chunk_size)
        return {"count": await agent.get_ingested_data_count(), "source": str(path)}
    except Exception as error:
        logger.exception("Document ingestion failed")
        raise HTTPException(500, f"文档入库失败：{error}") from error
    finally:
        agent.close()


@app.post("/api/ingest-code")
async def ingest_code(request: IngestCodeRequest) -> dict:
    agent = _agent(request.collection_name)
    try:
        await agent.ingest_code_from_source(request.source_path, cleanup_github_after=True)
        return {"count": await agent.get_ingested_data_count(), "source": request.source_path}
    except Exception as error:
        logger.exception("Code ingestion failed")
        raise HTTPException(500, f"代码入库失败：{error}") from error
    finally:
        agent.close()


@app.post("/api/generate")
async def generate(request: GenerateRequest) -> dict:
    agent = _agent(request.collection_name)
    try:
        content = await agent.generate_test_cases(request.query, request.num_retrieved_docs)
        quality = await agent.evaluate_test_case_quality(content, use_ai=True)
        return {"content": content, "collection_name": request.collection_name, "quality_gate": quality.as_dict()}
    except Exception as error:
        logger.exception("Test generation failed")
        raise HTTPException(500, f"测试用例生成失败：{error}") from error
    finally:
        agent.close()


@app.post("/api/quality-check")
async def quality_check(request: QualityCheckRequest) -> dict:
    """Evaluate existing generated Markdown without storing or automating it."""
    agent = _agent("quality_check")
    try:
        result = await agent.evaluate_test_case_quality(request.content, use_ai=request.use_ai)
        return result.as_dict()
    finally:
        agent.close()


@app.post("/api/agent-runs")
async def create_agent_run(request: AgentRunRequest) -> dict:
    job = await job_manager.create_job(request)
    return {"task_id": job.task_id, "status": job.status}


@app.get("/api/agent-runs/{task_id}")
async def get_agent_run(task_id: str) -> dict:
    job = job_manager.get_job(task_id)
    if not job:
        raise HTTPException(404, f"Task not found: {task_id}")
    return {
        "task_id": job.task_id,
        "status": job.status,
        "final_verdict": job.result.get("final_verdict") if job.result else None,
        "repair_rounds": job.result.get("repair_round", 0) if job.result else 0,
        "repair_history": job.result.get("repair_history", []) if job.result else [],
        "execution_result": job.result.get("execution_result") if job.result else None,
        "error": job.error,
    }


@app.get("/api/agent-runs/{task_id}/events")
async def stream_agent_events(task_id: str) -> StreamingResponse:
    job = job_manager.get_job(task_id)
    if not job:
        raise HTTPException(404, f"Task not found: {task_id}")

    async def event_generator():
        # Replay historical events first to prevent race condition
        for idx, ev in enumerate(list(job.events_history)):
            yield f"id: {idx}\nevent: {ev.get('event', 'message')}\ndata: {json.dumps(ev, default=str)}\n\n"

        if job.status in ("PASS", "REJECTED", "FAILED", "ERROR"):
            return

        queue: asyncio.Queue = asyncio.Queue()
        job.subscribers.append(queue)
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {ev.get('event', 'message')}\ndata: {json.dumps(ev, default=str)}\n\n"
                    if ev.get("event") in ("RUN_COMPLETED", "RUN_ERROR"):
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if queue in job.subscribers:
                job.subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/agent-runs/{task_id}/resume")
async def resume_agent_run(task_id: str, request: ResumeRequest) -> dict:
    return await job_manager.resume_job(task_id, request.decision)


def run() -> None:
    """Run the console locally. Credentials remain in the project .env file."""
    uvicorn.run("testteller.web.app:app", host="127.0.0.1", port=7860, reload=False)
