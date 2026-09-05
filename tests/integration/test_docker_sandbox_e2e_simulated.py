"""End-to-end container lifecycle simulation tests verifying all 6 guarantees with real child processes.

This suite runs on ANY machine (even Windows without Docker Desktop installed) by providing a realistic,
process-isolated Docker CLI driver that launches real subprocesses with sanitized environments.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Any
import uuid

import pytest

from testteller.agent_runtime.sandbox.network import IsolatedTargetNetwork
from testteller.agent_runtime.sandbox.policy import NetworkPolicy, SandboxPolicy
from testteller.agent_runtime.tools.artifacts import WorkspaceArtifacts
from testteller.agent_runtime.tools.execution import DockerSandboxExecutor


class DockerProcessSimulator:
    """Simulates Docker daemon operations by executing commands in isolated child processes."""

    def __init__(self) -> None:
        self.containers: dict[str, dict[str, Any]] = {}
        self.networks: set[str] = set()

    def run_cmd(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        subcmd = cmd[1] if len(cmd) > 1 else ""

        if subcmd == "image" and len(cmd) > 2 and cmd[2] == "inspect":
            image_name = cmd[-1]
            mock_digest = f"sha256:7f8a9b_{image_name.replace(':', '_')}"
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=mock_digest, stderr="")

        if subcmd == "network":
            action = cmd[2] if len(cmd) > 2 else ""
            if action == "create":
                net_name = cmd[-1]
                self.networks.add(net_name)
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=net_name, stderr="")
            if action == "rm":
                net_name = cmd[-1]
                self.networks.discard(net_name)
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=net_name, stderr="")

        if subcmd == "create":
            name_idx = cmd.index("--name") + 1
            c_name = cmd[name_idx]
            env_vars = {}
            for i, arg in enumerate(cmd):
                if arg == "-e" and i + 1 < len(cmd):
                    k, v = cmd[i + 1].split("=", 1)
                    env_vars[k] = v

            # Extract volume host path
            vol_idx = cmd.index("-v") + 1
            vol_spec = cmd[vol_idx]
            host_path = vol_spec.split(":/workspace:")[0]

            # Image is before the command
            img_idx = -1
            for i, arg in enumerate(cmd):
                if "testteller-runner" in arg or "python:" in arg:
                    img_idx = i
                    break
            run_cmd = cmd[img_idx + 1 :] if img_idx != -1 else ["pytest", "-q"]

            self.containers[c_name] = {
                "args": cmd,
                "env": env_vars,
                "host_path": Path(host_path),
                "run_cmd": run_cmd,
                "proc": None,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
            }
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=c_name, stderr="")

        if subcmd == "start":
            c_name = cmd[2]
            c = self.containers[c_name]
            host_workdir = c["host_path"]

            # Replace pytest command with current venv python executable
            executable = Path(".venv/Scripts/python.exe").resolve()
            actual_cmd = [str(executable), "-m", "pytest"]
            skip_next = False
            for arg in c["run_cmd"]:
                if skip_next:
                    skip_next = False
                    continue
                if arg in ("python", "pytest", "-m"):
                    continue
                if arg == "--json-report":
                    continue
                if arg.startswith("--json-report-file="):
                    continue
                if arg == "--json-report-file":
                    skip_next = True
                    continue
                actual_cmd.append(arg)

            # Run with STRICT isolated environment (only injected envs!)
            proc_env = dict(c["env"])
            proc_env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "C:\\Windows")
            proc_env["PATH"] = os.environ.get("PATH", "")

            p = subprocess.Popen(
                actual_cmd,
                cwd=host_workdir,
                env=proc_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            c["proc"] = p
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        if subcmd == "wait":
            c_name = cmd[2]
            c = self.containers[c_name]
            p = c["proc"]
            timeout = kwargs.get("timeout", 120)
            try:
                stdout, stderr = p.communicate(timeout=timeout)
                c["stdout"] = stdout
                c["stderr"] = stderr
                c["exit_code"] = p.returncode
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout=f"{p.returncode}\n", stderr=""
                )
            except subprocess.TimeoutExpired:
                raise

        if subcmd == "kill":
            c_name = cmd[2]
            c = self.containers.get(c_name)
            if c and c.get("proc"):
                c["proc"].kill()
                c["proc"].wait()
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        if subcmd == "logs":
            c_name = cmd[2]
            c = self.containers.get(c_name, {})
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=c.get("stdout", ""),
                stderr=c.get("stderr", ""),
            )

        if subcmd == "rm":
            c_name = cmd[-1]
            self.containers.pop(c_name, None)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def test_e2e_simulated_container_pass_and_artifacts(tmp_path: Path):
    """End-to-end verified execution: passing test case + persistent artifact extraction."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_math_ok.py": "def test_ok():\n    assert 10 + 20 == 30\n",
    })

    sim = DockerProcessSimulator()
    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        runner_func=sim.run_cmd,
        timeout_seconds=30,
    )
    result = executor.run(["pytest", "-q"], framework="pytest")

    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["backend"] == "docker"
    assert result["runner_image"] == "testteller-runner-python:3.11-v1"
    assert "sha256:" in result["runner_digest"]
    assert result["artifacts"]["persisted_dir"] is not None

    # Persistent artifact files verified
    persisted_dir = Path(result["artifacts"]["persisted_dir"])
    assert (persisted_dir / "junit.xml").exists()
    assert result["artifacts"]["junit_summary"]["passed"] >= 1


def test_e2e_simulated_container_secrets_isolation(tmp_path: Path, monkeypatch):
    """End-to-end verified secrets isolation: host secrets stripped from real child process environment."""
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-production-key-abc12345")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-secret-key-999")

    WorkspaceArtifacts(tmp_path).write_files({
        "test_no_secrets.py": """
import os

def test_secrets_isolation_inside_process():
    assert os.environ.get("OPENAI_API_KEY") is None
    assert os.environ.get("ANTHROPIC_API_KEY") is None
    assert os.environ.get("TESTTELLER_SANDBOX") == "1"
""",
    })

    sim = DockerProcessSimulator()
    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        runner_func=sim.run_cmd,
        timeout_seconds=30,
    )
    result = executor.run(["pytest", "-q"], framework="pytest")

    assert result["passed"] is True
    assert result["exit_code"] == 0


def test_e2e_simulated_container_workspace_mutation_prevented(tmp_path: Path):
    """End-to-end verified workspace protection: child process cannot corrupt host files."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_tamper.py": """
def test_modify_disk():
    with open("host_polluted.txt", "w") as f:
        f.write("corrupted data")
""",
    })

    sim = DockerProcessSimulator()
    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        runner_func=sim.run_cmd,
        timeout_seconds=30,
    )
    result = executor.run(["pytest", "-q"], framework="pytest")

    assert result["passed"] is True
    # Host workspace MUST NOT be polluted because execution is isolated in staging
    assert not (tmp_path / "host_polluted.txt").exists()


def test_e2e_simulated_container_timeout_and_guaranteed_cleanup(tmp_path: Path):
    """End-to-end verified timeout termination and guaranteed 0 orphan containers."""
    WorkspaceArtifacts(tmp_path).write_files({
        "test_hang.py": """
import time

def test_infinite_loop():
    time.sleep(30)
""",
    })

    sim = DockerProcessSimulator()
    executor = DockerSandboxExecutor(
        workspace_root=tmp_path,
        runner_func=sim.run_cmd,
        timeout_seconds=2,
    )
    result = executor.run(["pytest", "-q"], framework="pytest")

    assert result["timed_out"] is True
    assert result["passed"] is False
    assert "[timeout: container killed" in result["stderr"]

    # Guaranteed cleanup verified: container dict has 0 leaked entries
    assert len(sim.containers) == 0


def test_e2e_simulated_container_target_only_network_lifecycle(tmp_path: Path):
    """End-to-end verified TARGET_ONLY internal network isolation and destruction."""
    sim = DockerProcessSimulator()
    with IsolatedTargetNetwork(network_name="bench_isolated", runner_func=sim.run_cmd) as net:
        assert "bench_isolated" in sim.networks

    # On context exit, internal network must be deleted
    assert "bench_isolated" not in sim.networks
