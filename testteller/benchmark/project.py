"""Deterministic project isolation, Git checkout, and static frozen RAG management."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from testteller.benchmark.schema import ProjectManifest

logger = logging.getLogger(__name__)


class BenchmarkProjectManager:
    """Manages clean isolated workspaces, git commit checkouts, and static frozen RAG snapshots."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = (base_dir or Path.cwd()).resolve()

    def resolve_project_source(self, manifest: ProjectManifest) -> Path:
        """Resolve the source directory of the project manifest."""
        p = Path(manifest.repo_path)
        if not p.is_absolute():
            p = (self.base_dir / p).resolve()
        return p

    def ensure_project_repo(self, manifest: ProjectManifest) -> Path:
        """Ensure the project repository exists and is checked out to the exact pinned commit SHA."""
        target_dir = self.resolve_project_source(manifest)

        if not target_dir.exists():
            if not manifest.repo_url:
                raise FileNotFoundError(
                    f"Project directory {target_dir} not found and no repo_url provided in manifest '{manifest.name}'."
                )
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Cloning project %s from %s into %s...", manifest.name, manifest.repo_url, target_dir)
            proc = subprocess.run(
                ["git", "clone", manifest.repo_url, str(target_dir)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"Failed to clone {manifest.repo_url}: {proc.stderr}")

        # If it's a git repo, verify and checkout the exact commit SHA
        if (target_dir / ".git").exists():
            logger.debug("Checking out commit %s for %s...", manifest.commit_sha, manifest.name)
            # Fetch commit if not available locally
            checkout_proc = subprocess.run(
                ["git", "checkout", manifest.commit_sha],
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if checkout_proc.returncode != 0 and manifest.repo_url:
                # Try fetching
                subprocess.run(
                    ["git", "fetch", "origin", manifest.commit_sha],
                    cwd=str(target_dir),
                    capture_output=True,
                    timeout=60,
                )
                checkout_proc = subprocess.run(
                    ["git", "checkout", manifest.commit_sha],
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

            # Verify HEAD SHA
            head_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if head_proc.returncode != 0:
                raise RuntimeError(f"Failed to get git HEAD SHA for {manifest.name}: {head_proc.stderr.strip()}")
            current_sha = (head_proc.stdout or "").strip().lower()
            expected_sha = manifest.commit_sha.strip().lower()
            if current_sha != expected_sha:
                raise RuntimeError(
                    f"Commit mismatch for {manifest.name}: current HEAD is '{current_sha}', expected '{expected_sha}'. "
                    "Benchmark requires exact commit reproduction."
                )

        return target_dir

    def create_isolated_workspace(self, manifest: ProjectManifest, destination_dir: Path) -> Path:
        """Create a fresh, isolated copy of the project codebase for a benchmark run."""
        source_dir = self.ensure_project_repo(manifest)

        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)

        def ignore_patterns(dir_path: str, names: list[str]) -> set[str]:
            ignored = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", ".DS_Store", "tests", "test"}
            return set(names).intersection(ignored)

        for item in source_dir.iterdir():
            if item.name in {".git", ".venv", "__pycache__", ".pytest_cache", "tests", "test"}:
                continue
            dest = destination_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, ignore=ignore_patterns)
            else:
                shutil.copy2(item, dest)

        # Ensure conftest.py exists in the destination root so pythonpath includes workspace root and src
        conftest = destination_dir / "conftest.py"
        if not conftest.exists():
            conftest.write_text(
                "import sys, os\n"
                "root = os.path.abspath(os.path.dirname(__file__))\n"
                "if root not in sys.path:\n"
                "    sys.path.insert(0, root)\n"
                "src = os.path.join(root, 'src')\n"
                "if os.path.exists(src) and src not in sys.path:\n"
                "    sys.path.insert(0, src)\n",
                encoding="utf-8",
            )

        try:
            os.chmod(destination_dir, 0o777)

            for root, dirs, files in os.walk(destination_dir):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), 0o777)
                    except Exception:
                        pass
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), 0o777)
                    except Exception:
                        pass
        except Exception:
            pass

        return destination_dir


    def compute_corpus_hash(self, manifest: ProjectManifest) -> str:
        """Compute deterministic SHA256 corpus hash across all source files of the project."""
        source_dir = self.ensure_project_repo(manifest)
        hasher = hashlib.sha256()

        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", ".pytest_cache", "tests", "test"}]
            for f in sorted(files):
                if f.endswith((".py", ".md", ".rst", ".txt")):
                    file_path = Path(root) / f
                    try:
                        hasher.update(file_path.read_bytes())
                    except Exception:
                        pass

        return hasher.hexdigest()

    def get_static_rag_collection_name(self, manifest: ProjectManifest) -> str:
        """Generate an isolated, immutable collection name for static RAG snapshot."""
        short_sha = manifest.commit_sha[:8] if manifest.commit_sha else "static"
        return f"benchmark_v1_{manifest.name}_{short_sha}"

    def build_or_load_static_rag_snapshot(
        self,
        manifest: ProjectManifest,
        chroma_persist_dir: Path | None = None,
        llm_manager: Any | None = None,
    ) -> tuple[str, str]:
        """Index or verify the immutable static RAG snapshot collection with real corpus ingestion."""
        collection_name = self.get_static_rag_collection_name(manifest)
        corpus_hash = self.compute_corpus_hash(manifest)

        persist_path = chroma_persist_dir or (self.base_dir / "chroma_data")
        persist_path.mkdir(parents=True, exist_ok=True)

        meta_file = persist_path / f".frozen_rag_{collection_name}.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                if data.get("corpus_hash") == corpus_hash and data.get("frozen"):
                    expected_count = data.get("chunk_count")
                    if llm_manager and expected_count is not None:
                        from testteller.core.vector_store.chromadb_manager import ChromaDBManager
                        vs = ChromaDBManager(
                            llm_manager=llm_manager,
                            collection_name=collection_name,
                            persist_directory=str(persist_path),
                        )
                        if hasattr(vs, "collection") and vs.collection is not None:
                            actual_count = vs.collection.count()
                            if actual_count != expected_count:
                                raise RuntimeError(
                                    f"Chroma collection count mismatch for {collection_name}: "
                                    f"expected {expected_count}, got {actual_count}. Frozen RAG snapshot compromised."
                                )
                    logger.debug("Frozen RAG snapshot verified for %s", collection_name)
                    return collection_name, corpus_hash
            except Exception as e:
                if isinstance(e, RuntimeError):
                    raise
                pass

        # Ingest real OSS corpus files into ChromaDB
        source_dir = self.ensure_project_repo(manifest)
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        ids: list[str] = []

        def _chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[str]:
            if not text:
                return []
            chunks = []
            start = 0
            while start < len(text):
                end = start + chunk_size
                chunks.append(text[start:end])
                if end >= len(text):
                    break
                start += chunk_size - chunk_overlap
            return chunks

        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", ".pytest_cache", "tests", "test", "node_modules"}]
            for f in sorted(files):
                if f.endswith((".py", ".md", ".rst", ".txt")):
                    file_path = Path(root) / f
                    rel_path = str(file_path.relative_to(source_dir)).replace("\\", "/")
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        chunks = _chunk_text(content)
                        for idx, ch in enumerate(chunks):
                            docs.append(ch)
                            metas.append({
                                "source": rel_path,
                                "file_path": rel_path,
                                "file_type": file_path.suffix,
                                "type": "code",
                                "project": manifest.name,
                                "commit_sha": manifest.commit_sha,
                            })
                            ids.append(f"{manifest.name}_{rel_path}_{idx}")
                    except Exception as e:
                        logger.debug("Skipping unreadable file %s: %s", file_path, e)

        vs = None
        if docs and llm_manager:
            from testteller.core.vector_store.chromadb_manager import ChromaDBManager
            vs = ChromaDBManager(
                llm_manager=llm_manager,
                collection_name=collection_name,
                persist_directory=str(persist_path),
            )
            for i in range(0, len(docs), 50):
                vs.add_documents(
                    documents=docs[i : i + 50],
                    metadatas=metas[i : i + 50],
                    ids=ids[i : i + 50],
                )
            logger.info("Ingested %d chunks into frozen RAG collection %s", len(docs), collection_name)

        # 4. RAG freeze 前严格验证 collection count (e.g. 132 for cachetools, 431 for bottle)
        expected_chunk_count = len(docs)
        if vs is not None and expected_chunk_count > 0:
            actual_count = vs.collection.count() if (hasattr(vs, "collection") and vs.collection is not None) else 0
            if actual_count != expected_chunk_count:
                raise RuntimeError(
                    f"Chroma collection count mismatch for {collection_name}: "
                    f"expected {expected_chunk_count}, got {actual_count}. Freeze verification rejected."
                )
            logger.info(
                "Verified collection %s before freeze: expected %d == actual %d chunks",
                collection_name,
                expected_chunk_count,
                actual_count,
            )
        else:
            actual_count = expected_chunk_count

        # Write frozen marker metadata only after verification
        meta_content = {
            "collection_name": collection_name,
            "project_name": manifest.name,
            "commit_sha": manifest.commit_sha,
            "corpus_hash": corpus_hash,
            "chunk_count": actual_count,
            "expected_chunk_count": expected_chunk_count,
            "frozen": True,
            "read_only": True,
        }
        meta_file.write_text(json.dumps(meta_content, indent=2), encoding="utf-8")
        return collection_name, corpus_hash

    def get_provenance_metadata(
        self,
        manifest: ProjectManifest,
        model_name: str = "gemini-2.5-pro",
        corpus_hash: str | None = None,
        actual_backend: str | None = None,
        actual_runner_image: str | None = None,
        actual_runner_digest: str | None = None,
        actual_model_provider: str | None = None,
        actual_model_name: str | None = None,
        fallback_used: bool = False,
        testteller_commit: str | None = None,
    ) -> dict[str, Any]:
        """Produce the standard provenance dictionary with actual runtime properties."""
        from testteller.agent_runtime.tools.execution import get_current_git_commit

        actual_corpus_hash = corpus_hash or self.compute_corpus_hash(manifest)
        resolved_tt_commit = testteller_commit or get_current_git_commit()
        resolved_backend = actual_backend or "local"
        if resolved_backend.lower() == "local":
            resolved_image = None
            resolved_digest = None
        else:
            resolved_image = actual_runner_image or (
                "testteller-runner-python:3.11-v1" if manifest.language == "python" else "testteller-runner-node:18-v1"
            )
            resolved_digest = actual_runner_digest

        if fallback_used:
            resolved_provider = "offline"
            resolved_model = "offline-fallback"
        else:
            resolved_provider = actual_model_provider or "unknown"
            resolved_model = actual_model_name or model_name

        return {
            "project_name": manifest.name,
            "commit_sha": manifest.commit_sha,
            "target_commits": {manifest.name: manifest.commit_sha},
            "testteller_commit": resolved_tt_commit,
            "repo_url": manifest.repo_url or manifest.repo_path,
            "language": manifest.language,
            "test_framework": manifest.test_framework,
            "actual_backend": resolved_backend,
            "actual_runner_image": resolved_image,
            "actual_runner_digest": resolved_digest,
            "actual_model_provider": resolved_provider,
            "actual_model_name": resolved_model,
            "fallback_used": fallback_used,
            "runner_image": resolved_image,
            "runner_digest": resolved_digest,
            "rag_collection": self.get_static_rag_collection_name(manifest),
            "corpus_hash": actual_corpus_hash,
            "corpus_hashes": {manifest.name: actual_corpus_hash},
            "model_name": resolved_model,
        }
