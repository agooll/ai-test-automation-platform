from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from testteller.benchmark.project import BenchmarkProjectManager
from testteller.benchmark.schema import ProjectManifest


def test_ensure_project_repo_commit_mismatch_fails_fast(tmp_path: Path):
    mgr = BenchmarkProjectManager(base_dir=tmp_path)
    manifest = ProjectManifest(
        name="test_proj",
        repo_path="test_proj",
        commit_sha="0123456789abcdef0123456789abcdef01234567",
        repo_url="https://github.com/example/repo.git",
        language="python",
        test_framework="pytest",
    )

    proj_dir = tmp_path / "test_proj"
    proj_dir.mkdir(parents=True)
    git_dir = proj_dir / ".git"
    git_dir.mkdir()

    # Mock subprocess.run to return a different HEAD SHA
    mock_rev_parse = MagicMock()
    mock_rev_parse.returncode = 0
    mock_rev_parse.stdout = "fedcba9876543210fedcba9876543210fedcba98\n"

    with patch("subprocess.run", return_value=mock_rev_parse):
        with pytest.raises(RuntimeError) as exc_info:
            mgr.ensure_project_repo(manifest)
        assert "Commit mismatch" in str(exc_info.value)
        assert "Benchmark requires exact commit reproduction" in str(exc_info.value)


def test_ensure_project_repo_commit_match_succeeds(tmp_path: Path):
    mgr = BenchmarkProjectManager(base_dir=tmp_path)
    expected_sha = "0123456789abcdef0123456789abcdef01234567"
    manifest = ProjectManifest(
        name="test_proj",
        repo_path="test_proj",
        commit_sha=expected_sha,
        repo_url="https://github.com/example/repo.git",
        language="python",
        test_framework="pytest",
    )

    proj_dir = tmp_path / "test_proj"
    proj_dir.mkdir(parents=True)
    git_dir = proj_dir / ".git"
    git_dir.mkdir()

    mock_rev_parse = MagicMock()
    mock_rev_parse.returncode = 0
    mock_rev_parse.stdout = f"{expected_sha}\n"

    with patch("subprocess.run", return_value=mock_rev_parse):
        repo_path = mgr.ensure_project_repo(manifest)
        assert repo_path == proj_dir


def test_build_static_rag_snapshot_count_mismatch_raises(tmp_path: Path):
    """Verify that if Chroma collection count != expected chunks, RuntimeError is raised."""
    mgr = BenchmarkProjectManager(base_dir=tmp_path)
    manifest = ProjectManifest(
        name="test_proj",
        repo_path="test_proj",
        commit_sha="0123456789abcdef0123456789abcdef01234567",
        language="python",
        test_framework="pytest",
    )

    proj_dir = tmp_path / "test_proj"
    proj_dir.mkdir(parents=True)
    git_dir = proj_dir / ".git"
    git_dir.mkdir()
    (proj_dir / "mod.py").write_text("def hello(): return 'world'\n", encoding="utf-8")

    mock_llm = MagicMock()
    mock_vs = MagicMock()
    mock_vs.collection.count.return_value = 999  # Mismatch: expected 1 chunk, got 999

    mock_rev_parse = MagicMock(returncode=0, stdout=f"{manifest.commit_sha}\n")

    with patch("subprocess.run", return_value=mock_rev_parse), \
         patch("testteller.core.vector_store.chromadb_manager.ChromaDBManager", return_value=mock_vs):
        with pytest.raises(RuntimeError, match="Chroma collection count mismatch"):
            mgr.build_or_load_static_rag_snapshot(
                manifest,
                chroma_persist_dir=tmp_path / "chroma",
                llm_manager=mock_llm,
            )


def test_build_static_rag_snapshot_count_match_freezes(tmp_path: Path):
    """Verify that when Chroma collection count == expected chunks, snapshot is frozen."""
    mgr = BenchmarkProjectManager(base_dir=tmp_path)
    manifest = ProjectManifest(
        name="test_proj",
        repo_path="test_proj",
        commit_sha="0123456789abcdef0123456789abcdef01234567",
        language="python",
        test_framework="pytest",
    )

    proj_dir = tmp_path / "test_proj"
    proj_dir.mkdir(parents=True)
    git_dir = proj_dir / ".git"
    git_dir.mkdir()
    (proj_dir / "mod.py").write_text("def hello(): return 'world'\n", encoding="utf-8")

    mock_llm = MagicMock()
    mock_vs = MagicMock()
    mock_vs.collection.count.return_value = 1  # Exactly 1 chunk expected

    mock_rev_parse = MagicMock(returncode=0, stdout=f"{manifest.commit_sha}\n")

    with patch("subprocess.run", return_value=mock_rev_parse), \
         patch("testteller.core.vector_store.chromadb_manager.ChromaDBManager", return_value=mock_vs):
        col_name, c_hash = mgr.build_or_load_static_rag_snapshot(
            manifest,
            chroma_persist_dir=tmp_path / "chroma",
            llm_manager=mock_llm,
        )
        assert col_name.startswith("benchmark_v1_test_proj_")
        assert len(c_hash) == 64

        meta_file = tmp_path / "chroma" / f".frozen_rag_{col_name}.json"
        assert meta_file.exists()
        import json
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        assert data["frozen"] is True
        assert data["chunk_count"] == 1
        assert data["expected_chunk_count"] == 1

