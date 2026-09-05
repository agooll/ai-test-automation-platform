"""Unit tests for Stage 2 Docker Sandbox: Policy, Workspace Staging, Lifecycle, and Artifacts."""

import os
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from testteller.agent_runtime.sandbox.artifacts import ArtifactExtractor
from testteller.agent_runtime.sandbox.lifecycle import ContainerLifecycleManager
from testteller.agent_runtime.sandbox.network import IsolatedTargetNetwork
from testteller.agent_runtime.sandbox.policy import NetworkPolicy, SandboxPolicy
from testteller.agent_runtime.sandbox.workspace import PerRunWorkspace
from testteller.agent_runtime.tools.execution import (
    DockerSandboxExecutor,
    LocalSubprocessExecutor,
    create_test_executor,
    ensure_reporting_command,
)


# ============================================================================
# Guarantee 1: Secrets Isolation (Deny-by-default environment)
# ============================================================================

def test_secrets_isolation_strips_sensitive_host_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-token-12345")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("CUSTOM_ALLOWED_VAR", "my-safe-value")

    policy = SandboxPolicy(allowed_env_vars=["CUSTOM_ALLOWED_VAR"])
    env = policy.build_env()

    # Sensitive credentials must NEVER be present
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env

    # Defaults and explicit allowlist must be present
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["TESTTELLER_SANDBOX"] == "1"
    assert env["CI"] == "1"
    assert env["CUSTOM_ALLOWED_VAR"] == "my-safe-value"


def test_secrets_isolation_not_leaked_in_docker_args(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "super-sensitive-key")
    policy = SandboxPolicy()
    mgr = ContainerLifecycleManager(policy=policy, task_id="sec01")
    args = mgr.build_create_args("testteller-runner-python:3.11-v1", ["pytest"], tmp_path)

    full_args_str = " ".join(args)
    assert "super-sensitive-key" not in full_args_str
    assert "OPENAI_API_KEY" not in full_args_str
    assert "-e PYTHONUNBUFFERED=1" in full_args_str


# ============================================================================
# Guarantee 2: Workspace Protection & Staging Isolation (PerRunWorkspace)
# ============================================================================

def test_per_run_workspace_copies_files_and_excludes_sensitive_dirs(tmp_path: Path):
    source = tmp_path / "source_project"
    source.mkdir()
    (source / "test_math.py").write_text("def test_add(): assert 1 + 1 == 2", encoding="utf-8")
    (source / "README.md").write_text("Hello project", encoding="utf-8")

    git_dir = source / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

    pycache_dir = source / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "module.cpython-311.pyc").write_bytes(b"compiled")

    with PerRunWorkspace(source_workspace=source, task_id="test_run_1") as staged:
        staging_dir = staged.staging_dir
        assert staging_dir is not None
        assert staging_dir.exists()
        assert staging_dir != source

        # Required source files copied
        assert (staging_dir / "test_math.py").exists()
        assert (staging_dir / "README.md").exists()

        # Heavy/sensitive directories excluded
        assert not (staging_dir / ".git").exists()
        assert not (staging_dir / "__pycache__").exists()

        # Mutating staging directory does NOT touch original workspace
        (staging_dir / "generated_corrupted.txt").write_text("corrupted content", encoding="utf-8")
        (staging_dir / "test_math.py").unlink()
        assert (source / "test_math.py").exists()
        assert not (source / "generated_corrupted.txt").exists()

    # Staging directory must be cleaned up on context exit
    assert not staging_dir.exists()


# ============================================================================
# Guarantee 3: Guaranteed Lifecycle & Cleanup (No Orphan Containers)
# ============================================================================

def test_container_lifecycle_full_sequence(tmp_path: Path):
    calls = []

    def mock_runner(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        if "wait" in cmd:
            mock_proc.stdout = "0\n"
        elif "logs" in cmd:
            mock_proc.stdout = "3 passed in 0.10s"
            mock_proc.stderr = ""
        else:
            mock_proc.stdout = ""
            mock_proc.stderr = ""
        return mock_proc

    policy = SandboxPolicy(timeout_seconds=30, operation_timeout=15)
    mgr = ContainerLifecycleManager(policy=policy, task_id="run42", runner_func=mock_runner)
    res = mgr.run_container("testteller-runner-python:3.11-v1", ["pytest"], tmp_path)

    assert res["exit_code"] == 0
    assert res["timed_out"] is False
    assert "3 passed" in res["stdout"]

    # Verify explicit 5-stage lifecycle call sequence
    assert calls[0][0][1] == "create"
    assert calls[0][1].get("timeout") == 15  # control plane timeout enforced!
    assert calls[1][0] == ["docker", "start", mgr.container_name]
    assert calls[1][1].get("timeout") == 15
    assert calls[2][0] == ["docker", "wait", mgr.container_name]
    assert calls[2][1].get("timeout") == 30  # execution timeout!
    assert calls[3][0] == ["docker", "logs", mgr.container_name]
    assert calls[3][1].get("timeout") == 15
    assert calls[4][0] == ["docker", "rm", "-f", mgr.container_name]
    assert calls[4][1].get("timeout") == 15


def test_container_lifecycle_timeout_kills_and_removes(tmp_path: Path):
    calls = []

    def mock_runner(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[1] == "wait":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Partial output before timeout"
        mock_proc.stderr = ""
        return mock_proc

    policy = SandboxPolicy(timeout_seconds=5)
    mgr = ContainerLifecycleManager(policy=policy, task_id="timeout_task", runner_func=mock_runner)
    res = mgr.run_container("testteller-runner-python:3.11-v1", ["pytest"], tmp_path)

    assert res["timed_out"] is True
    assert res["exit_code"] is None
    assert "[timeout: container killed after 5s]" in res["stderr"]

    # Verify docker kill and docker rm -f were called
    kill_called = any(c == ["docker", "kill", mgr.container_name] for c in calls)
    rm_called = any(c == ["docker", "rm", "-f", mgr.container_name] for c in calls)
    assert kill_called is True
    assert rm_called is True


# ============================================================================
# Guarantee 4: Network Isolation Policies
# ============================================================================

def test_network_policy_none(tmp_path: Path):
    policy = SandboxPolicy(network_policy=NetworkPolicy.NONE)
    mgr = ContainerLifecycleManager(policy=policy)
    args = mgr.build_create_args("testteller-runner-python:3.11-v1", ["pytest"], tmp_path)
    assert "--network=none" in args


def test_network_policy_bridge(tmp_path: Path):
    policy = SandboxPolicy(network_policy=NetworkPolicy.BRIDGE)
    mgr = ContainerLifecycleManager(policy=policy)
    args = mgr.build_create_args("testteller-runner-python:3.11-v1", ["pytest"], tmp_path)
    assert "--network=bridge" in args


def test_network_policy_target_only(tmp_path: Path):
    policy = SandboxPolicy(
        network_policy=NetworkPolicy.TARGET_ONLY,
        target_host="192.168.1.100",
        target_network="custom-test-net",
    )
    mgr = ContainerLifecycleManager(policy=policy)
    args = mgr.build_create_args("testteller-runner-python:3.11-v1", ["pytest"], tmp_path)
    assert "--network=custom-test-net" in args
    assert "--add-host" in args
    assert "target:192.168.1.100" in args


def test_isolated_target_network_lifecycle():
    calls = []
    def mock_runner(cmd, **kwargs):
        calls.append(list(cmd))
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        return mock_proc

    with IsolatedTargetNetwork(network_name="bench_internal", runner_func=mock_runner) as net:
        target_name = net.attach_target_container(
            image="target-service:v1",
            container_name="my_target",
            env={"PORT": "8080"},
        )
        assert target_name == "my_target"

    assert calls[0] == ["docker", "network", "create", "--internal", "bench_internal"]
    assert calls[1][:5] == ["docker", "run", "-d", "--name", "my_target"]
    assert "--network" in calls[1]
    assert "bench_internal" in calls[1]
    assert "--network-alias" in calls[1]
    assert "target-app" in calls[1]
    assert calls[2] == ["docker", "rm", "-f", "my_target"]
    assert calls[3] == ["docker", "network", "rm", "bench_internal"]


# ============================================================================
# Guarantee 5: Resource & Filesystem Enforcement
# ============================================================================

def test_resource_limits_and_read_only_rootfs(tmp_path: Path):
    policy = SandboxPolicy(
        memory_limit="256m",
        cpus_limit="0.5",
        pids_limit=50,
        read_only_rootfs=True,
    )
    mgr = ContainerLifecycleManager(policy=policy)
    args = mgr.build_create_args("testteller-runner-python:3.11-v1", ["pytest"], tmp_path)

    assert "--memory=256m" in args
    assert "--cpus=0.5" in args
    assert "--pids-limit=50" in args
    assert "--security-opt=no-new-privileges" in args
    assert "--cap-drop=ALL" in args
    assert "--read-only" in args
    assert "--tmpfs" in args
    assert "--user" in args
    assert "1000:1000" in args


# ============================================================================
# Guarantee 6: Artifact Extraction, Persistence & Benchmark Fail-Fast
# ============================================================================

def test_artifact_extractor_parses_junit_and_json(tmp_path: Path):
    junit_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="pytest" errors="0" failures="1" skipped="1" tests="4" time="0.25">
        <testcase classname="test_api" name="test_get" time="0.05" />
        <testcase classname="test_api" name="test_post" time="0.10">
            <failure message="assert 500 == 200">AssertionError</failure>
        </testcase>
        <testcase classname="test_api" name="test_skip" time="0.00">
            <skipped />
        </testcase>
        <testcase classname="test_api" name="test_delete" time="0.10" />
    </testsuite>
</testsuites>
"""
    (tmp_path / "junit.xml").write_text(junit_content, encoding="utf-8")
    (tmp_path / ".report.json").write_text('{"summary": {"passed": 2, "failed": 1}}', encoding="utf-8")
    (tmp_path / "coverage.json").write_text('{"totals": {"percent_covered": 85.5}}', encoding="utf-8")

    artifacts = ArtifactExtractor.extract_from_dir(tmp_path)
    assert artifacts["junit_xml"] is not None
    assert artifacts["junit_summary"] == {
        "tests": 4,
        "passed": 2,
        "failures": 1,
        "errors": 0,
        "skipped": 1,
        "time_seconds": 0.25,
    }
    assert artifacts["json_report"]["summary"]["passed"] == 2
    assert artifacts["coverage"]["totals"]["percent_covered"] == 85.5
    assert "junit.xml" in artifacts["captured_files"]
    assert ".report.json" in artifacts["captured_files"]
    assert "coverage.json" in artifacts["captured_files"]


def test_artifact_extract_and_persist_copies_files(tmp_path: Path):
    source_staging = tmp_path / "staging"
    source_staging.mkdir()
    (source_staging / "junit.xml").write_text("<testsuites><testsuite tests='1' failures='0'/></testsuites>", encoding="utf-8")
    (source_staging / "coverage.xml").write_text("<coverage/>", encoding="utf-8")

    persistent_dir = tmp_path / "persistent_artifacts"

    artifacts = ArtifactExtractor.extract_and_persist(source_staging, persistent_dir)
    assert artifacts["persisted_dir"] == str(persistent_dir)
    assert "junit.xml" in artifacts["persisted_files"]
    assert "coverage.xml" in artifacts["persisted_files"]

    # Verify physical file existence in persistent dir
    assert (persistent_dir / "junit.xml").exists()
    assert (persistent_dir / "coverage.xml").exists()


def test_ensure_reporting_command_augments_pytest():
    base_cmd = ["python", "-m", "pytest", "-q"]
    augmented = ensure_reporting_command(
        base_cmd,
        framework="pytest",
        generate_coverage=True,
        include_json_report=True,
    )

    assert any("--junitxml=junit.xml" in arg for arg in augmented)
    assert any("--json-report" in arg for arg in augmented)
    assert any("--cov" in arg for arg in augmented)


def test_benchmark_fail_fast_when_docker_missing(tmp_path: Path):
    with patch("testteller.agent_runtime.tools.execution.is_docker_available", return_value=False):
        # Strict benchmark requirement: must fail immediately, no silent fallback
        with pytest.raises(RuntimeError, match="Docker sandbox executor requested"):
            create_test_executor(tmp_path, backend="docker")


def test_docker_sandbox_executor_default_uses_pinned_runner(tmp_path: Path):
    def mock_runner(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        if "wait" in cmd:
            mock_proc.stdout = "0\n"
        elif "logs" in cmd:
            mock_proc.stdout = "All tests passed!"
            mock_proc.stderr = ""
        else:
            mock_proc.stdout = ""
            mock_proc.stderr = ""
        return mock_proc

    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        runner_func=mock_runner,
    )
    # Default without explicit parameters must use testteller-runner-python:3.11-v1
    assert executor.resolve_image("pytest") == "testteller-runner-python:3.11-v1"

    result = executor.run(["pytest", "-q"], framework="pytest")
    assert result["passed"] is True
    assert result["backend"] == "docker"
    assert result["runner_image"] == "testteller-runner-python:3.11-v1"
    assert result["runner_version"] == "3.11-v1"
    assert "runner_digest" in result
    assert "repo_commit" in result
    assert "artifacts" in result
    assert result["artifacts"]["persisted_dir"] is not None
