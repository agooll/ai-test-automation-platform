from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from testteller.agent_runtime.tools.artifacts import WorkspaceArtifacts
from testteller.agent_runtime.tools.execution import (
    BaseTestExecutor,
    DockerSandboxExecutor,
    LocalSubprocessExecutor,
    SafeTestExecutor,
    create_test_executor,
    is_docker_available,
)


def test_safe_executor_runs_only_inside_workspace(tmp_path: Path):
    WorkspaceArtifacts(tmp_path).write_files({"test_ok.py": "def test_ok():\n    assert True\n"})
    result = SafeTestExecutor(tmp_path).run(
        ["python", "-m", "pytest", "-q"], framework="pytest"
    )
    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["backend"] == "local"
    assert "artifacts" in result


def test_safe_executor_rejects_unapproved_command(tmp_path: Path):
    with pytest.raises(ValueError, match="not allowed"):
        SafeTestExecutor(tmp_path).run(["powershell", "-Command", "Get-Date"])


@pytest.mark.parametrize("command", [
    ["python", "-c", "print('escape')"],
    ["python", "-m", "pip", "install", "x"],
])
def test_safe_executor_rejects_interpreter_escape_hatches(tmp_path: Path, command):
    with pytest.raises(ValueError):
        SafeTestExecutor(tmp_path).run(command)


def test_artifacts_reject_path_escape(tmp_path: Path):
    with pytest.raises(ValueError, match="escapes workspace"):
        WorkspaceArtifacts(tmp_path).write_files({"..\\outside.txt": "blocked"})


def test_docker_command_construction(tmp_path: Path):
    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        memory_limit="256m",
        cpus_limit="0.5",
        pids_limit=50,
        allow_network=False,
    )
    cmd = executor.build_docker_command(
        ["python.exe", "-m", "pytest", "-q"],
        workdir=tmp_path,
        framework="pytest",
    )
    assert cmd[0] == "docker"
    assert cmd[1] == "run"
    assert "--rm" in cmd
    assert "--memory=256m" in cmd
    assert "--cpus=0.5" in cmd
    assert "--pids-limit=50" in cmd
    assert "--network=none" in cmd
    assert "--security-opt=no-new-privileges" in cmd
    assert "--cap-drop=ALL" in cmd
    assert "python:3.11-slim" in cmd
    # Command normalized from python.exe to python
    assert cmd[-4:] == ["python", "-m", "pytest", "-q"]


def test_docker_command_node_framework(tmp_path: Path):
    executor = DockerSandboxExecutor(workspace_root=tmp_path)
    cmd = executor.build_docker_command(
        ["npm.cmd", "test"],
        workdir=tmp_path,
        framework="jest",
    )
    assert "node:18-slim" in cmd
    assert cmd[-2:] == ["npm", "test"]


def test_docker_executor_run_mocked(tmp_path: Path):
    executor = DockerSandboxExecutor(workspace_root=tmp_path)
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "1 passed in 0.05s"
    mock_res.stderr = ""

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        res = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")
        assert res["passed"] is True
        assert res["exit_code"] == 0
        assert res["backend"] == "docker"
        assert "1 passed" in res["stdout"]
        assert mock_run.call_count >= 1


def test_docker_executor_timeout_handling(tmp_path: Path):
    executor = DockerSandboxExecutor(workspace_root=tmp_path, timeout_seconds=5)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=5)):
        res = executor.run(["python", "-m", "pytest", "-q"], framework="pytest")
        assert res["passed"] is False
        assert res["timed_out"] is True
        assert res["backend"] == "docker"
        assert "[timeout: container killed" in res["stderr"]


def test_create_test_executor_auto_fallback(tmp_path: Path):
    # When docker is not available, auto should fallback to local
    with patch("testteller.agent_runtime.tools.execution.is_docker_available", return_value=False):
        exec_inst = create_test_executor(tmp_path, backend="auto")
        assert isinstance(exec_inst, LocalSubprocessExecutor)


def test_create_test_executor_auto_docker(tmp_path: Path):
    # When docker is available, auto should use DockerSandboxExecutor
    with patch("testteller.agent_runtime.tools.execution.is_docker_available", return_value=True):
        exec_inst = create_test_executor(tmp_path, backend="auto")
        assert isinstance(exec_inst, DockerSandboxExecutor)


def test_create_test_executor_explicit_docker_error_when_unavailable(tmp_path: Path):
    # When docker is explicitly requested but unavailable, raise RuntimeError
    with patch("testteller.agent_runtime.tools.execution.is_docker_available", return_value=False):
        with pytest.raises(RuntimeError, match="Docker sandbox executor requested"):
            create_test_executor(tmp_path, backend="docker")


def test_create_test_executor_explicit_local(tmp_path: Path):
    exec_inst = create_test_executor(tmp_path, backend="local")
    assert isinstance(exec_inst, LocalSubprocessExecutor)
