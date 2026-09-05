"""Real Docker integration tests executed against a live Docker daemon.

These tests are skipped gracefully on environments without a Docker daemon (e.g. Windows dev boxes without Docker Desktop),
and run fully on Linux/CI environments with Docker installed.
"""

import os
from pathlib import Path
import subprocess

import pytest

from testteller.agent_runtime.sandbox.network import IsolatedTargetNetwork
from testteller.agent_runtime.sandbox.policy import NetworkPolicy, SandboxPolicy
from testteller.agent_runtime.tools.artifacts import WorkspaceArtifacts
from testteller.agent_runtime.tools.execution import (
    DockerSandboxExecutor,
    is_docker_available,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_docker_available(),
        reason="Docker CLI or daemon is not available on this host.",
    ),
]


def test_real_docker_pass_and_artifacts(tmp_path: Path):
    """Test real container execution with passing tests and persistent artifact extraction."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_simple.py": "def test_addition():\n    assert 2 + 2 == 4\n",
    })

    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        timeout_seconds=60,
    )
    result = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")

    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["backend"] == "docker"
    assert "runner_digest" in result
    assert "artifacts" in result
    assert result["artifacts"]["persisted_dir"] is not None


def test_real_docker_fail_case(tmp_path: Path):
    """Test real container execution with failing assertions."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_fail.py": "def test_failing_assert():\n    assert 1 == 2, 'intentional failure'\n",
    })

    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        timeout_seconds=60,
    )
    result = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")

    assert result["passed"] is False
    assert result["exit_code"] != 0
    assert result["backend"] == "docker"
    assert "intentional failure" in result["stdout"] or "intentional failure" in result["stderr"]


def test_real_docker_secrets_isolation(tmp_path: Path, monkeypatch):
    """Verify secrets inside host environment are NEVER leaked to the real container."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sensitive-production-token-12345")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_super_secret_github_token")

    WorkspaceArtifacts(tmp_path).write_files({
        "test_secrets.py": """
import os

def test_secrets_are_absent():
    assert os.environ.get("OPENAI_API_KEY") is None, "OPENAI_API_KEY leaked into container!"
    assert os.environ.get("GITHUB_TOKEN") is None, "GITHUB_TOKEN leaked into container!"
    assert os.environ.get("TESTTELLER_SANDBOX") == "1"
    assert os.environ.get("PYTHONUNBUFFERED") == "1"
""",
    })

    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        timeout_seconds=60,
    )
    result = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")

    assert result["passed"] is True
    assert result["exit_code"] == 0


def test_real_docker_network_none_blocks_egress(tmp_path: Path):
    """Verify NetworkPolicy.NONE strictly blocks outbound socket connections."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_network.py": """
import socket
import pytest

def test_socket_connect_fails_in_offline_sandbox():
    with pytest.raises(Exception):
        # Attempt connecting to Cloudflare public DNS
        sock = socket.create_connection(("1.1.1.1", 80), timeout=2)
        sock.close()
""",
    })

    policy = SandboxPolicy(network_policy=NetworkPolicy.NONE)
    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        policy=policy,
        timeout_seconds=30,
    )
    result = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")

    assert result["passed"] is True
    assert result["exit_code"] == 0


def test_real_docker_workspace_mutation_prevented(tmp_path: Path):
    """Verify test running in container cannot mutate host workspace files directly."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_tamper.py": """
def test_attempt_tampering():
    with open("host_tampered.txt", "w") as f:
        f.write("malicious overwrite")
""",
    })

    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        timeout_seconds=30,
    )
    result = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")

    assert result["passed"] is True
    # Host workspace must NOT have been written because of staging isolation
    assert not (tmp_path / "host_tampered.txt").exists()


def test_real_docker_timeout_kills_and_cleans(tmp_path: Path):
    """Verify timeout kills the container and leaves zero orphaned containers."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_hang.py": """
import time

def test_infinite_loop():
    time.sleep(30)
""",
    })

    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        timeout_seconds=3,
    )
    result = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")

    assert result["timed_out"] is True
    assert result["passed"] is False
    assert "[timeout: container killed" in result["stderr"]

    # Verify container name is clean in docker ps -a
    container_name = result.get("container_name")
    if container_name:
        check_res = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert container_name not in (check_res.stdout or "")


def test_real_docker_target_only_closed_loop(tmp_path: Path):
    """Verify TARGET_ONLY internal network connects runner strictly to target container."""
    net_name = f"test_net_{tmp_path.name[:8]}"
    with IsolatedTargetNetwork(network_name=net_name) as net:
        # Start a lightweight HTTP server as target-app container
        net.attach_target_container(
            image="python:3.11-slim",
            container_name=f"target_{tmp_path.name[:8]}",
            command=["python", "-m", "http.server", "8000"],
        )
        import time
        time.sleep(1)

        WorkspaceArtifacts(tmp_path).write_files({
            "test_target.py": """
import httpx
import pytest

def test_reach_target_app():
    # Calling target-app inside the internal network succeeds
    res = httpx.get("http://target-app:8000", timeout=5)
    assert res.status_code == 200

def test_cannot_reach_external_internet():
    # Calling external internet is strictly blocked by --internal
    with pytest.raises(Exception):
        httpx.get("http://1.1.1.1", timeout=2)
""",
        })

        policy = SandboxPolicy(
            network_policy=NetworkPolicy.TARGET_ONLY,
            target_network=net_name,
            timeout_seconds=30,
        )
        executor = DockerSandboxExecutor(workspace_root=tmp_path, policy=policy)
        result = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")

        assert result["passed"] is True
        assert result["exit_code"] == 0
