from pathlib import Path

import pytest

from testteller.agent_runtime.tools.execution import SafeTestExecutor
from testteller.agent_runtime.tools.artifacts import WorkspaceArtifacts


def test_safe_executor_runs_only_inside_workspace(tmp_path: Path):
    WorkspaceArtifacts(tmp_path).write_files({"test_ok.py": "def test_ok():\n    assert True\n"})
    result = SafeTestExecutor(tmp_path).run(
        ["python", "-m", "pytest", "-q"], framework="pytest"
    )
    assert result["passed"] is True
    assert result["exit_code"] == 0


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
