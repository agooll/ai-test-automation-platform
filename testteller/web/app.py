"""Local-only FastAPI console that reuses the TestTeller agent workflow."""

import logging
import os
import re
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from testteller.generator_agent.agent.testteller_agent import TestTellerAgent

logger = logging.getLogger(__name__)
APP_DIR = Path(__file__).resolve().parent
COLLECTION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

app = FastAPI(title="TestTeller Console", version="0.1.0")
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
    return {"status": "ok", "provider": os.getenv("LLM_PROVIDER", "gemini")}


@app.post("/api/status")
async def status(request: CollectionRequest) -> dict:
    agent = _agent(request.collection_name)
    try:
        count = await agent.get_ingested_data_count()
        return {
            "collection_name": request.collection_name,
            "count": count,
            "provider": agent.llm_manager.provider,
            "storage": agent.vector_store.db_path if not agent.vector_store.use_remote else "remote ChromaDB",
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


def run() -> None:
    """Run the console locally. Credentials remain in the project .env file."""
    uvicorn.run("testteller.web.app:app", host="127.0.0.1", port=7860, reload=False)
