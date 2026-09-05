"""Safe, bounded execution of generated test projects with Local and Docker Sandbox backends."""

from __future__ import annotations

import abc
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Sequence

from ..sandbox.artifacts import ArtifactExtractor
from ..sandbox.lifecycle import ContainerLifecycleManager
from ..sandbox.policy import NetworkPolicy, SandboxPolicy
from ..sandbox.workspace import PerRunWorkspace

logger = logging.getLogger(__name__)


def get_current_git_commit() -> str:
    """Safely obtain the current git HEAD commit SHA."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return (res.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def ensure_reporting_command(
    command: Sequence[str],
    framework: str = "pytest",
    generate_coverage: bool = False,
    include_json_report: bool = False,
) -> list[str]:
    """Augment test command with standard reporting flags so artifacts are produced."""
    cmd = list(command)
    fw = framework.lower()
    cmd_str = " ".join(cmd)
    if fw == "pytest" or "pytest" in cmd_str:
        if not any("--junitxml" in arg for arg in cmd):
            cmd.append("--junitxml=junit.xml")
        if include_json_report and not any("--json-report" in arg for arg in cmd):
            cmd.extend(["--json-report", "--json-report-file=.report.json"])
        if generate_coverage and not any("--cov" in arg for arg in cmd):
            cmd.extend(["--cov", "--cov-report=xml:coverage.xml"])
    return cmd


class BaseTestExecutor(abc.ABC):
    """Abstract base class for test execution environments."""

    def __init__(
        self,
        workspace_root: str | Path,
        timeout_seconds: int = 120,
        max_output_chars: int = 30_000,
        persistent_artifacts_dir: str | Path | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self.persistent_artifacts_dir = (
            Path(persistent_artifacts_dir).resolve()
            if persistent_artifacts_dir
            else self.workspace_root / "artifacts"
        )

    @abc.abstractmethod
    def run(
        self,
        command: Sequence[str],
        cwd: str | Path | None = None,
        framework: str = "pytest",
    ) -> dict[str, Any]:
        """Run the test command and return standardized execution result dictionary."""
        raise NotImplementedError

    def _ensure_inside(self, path: Path) -> None:
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError(f"Working directory escapes workspace: {path}") from exc
        if not path.is_dir():
            raise ValueError(f"Working directory does not exist: {path}")

    @staticmethod
    def _text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        return value.decode(errors="replace") if isinstance(value, bytes) else value


class LocalSubprocessExecutor(BaseTestExecutor):
    """Run approved test commands locally inside the designated workspace."""

    DEFAULT_ALLOWED = {
        "pytest": {"pytest", "python", "py", "pytest.exe", "python.exe", "py.exe"},
        "jest": {"jest", "npx", "npm", "node", "jest.cmd", "npx.cmd", "npm.cmd", "node.exe"},
        "playwright": {"pytest", "npx", "playwright", "npx.cmd", "playwright.cmd"},
        "maven": {"mvn", "mvnw", "mvnw.cmd"},
    }

    def run(
        self,
        command: Sequence[str],
        cwd: str | Path | None = None,
        framework: str = "pytest",
    ) -> dict[str, Any]:
        if not command:
            raise ValueError("Test command cannot be empty")
        workdir = (Path(cwd) if cwd else self.workspace_root).resolve()
        self._ensure_inside(workdir)

        executable = Path(str(command[0])).name.lower()
        allowed = {item.lower() for item in self.DEFAULT_ALLOWED.get(framework.lower(), set())}
        if executable not in allowed:
            raise ValueError(f"Command is not allowed for {framework}: {command[0]}")
        self._validate_arguments([str(item) for item in command], framework.lower())

        augmented_cmd = ensure_reporting_command(command, framework=framework)

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [str(item) for item in augmented_cmd],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
            timed_out = False
            return_code = completed.returncode
            stdout, stderr = completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            return_code = None
            stdout = self._text(exc.stdout)
            stderr = self._text(exc.stderr) + "\n[timeout]"

        output = (stdout or "")[-self.max_output_chars :]
        error_output = (stderr or "")[-self.max_output_chars :]

        persist_dir = self.persistent_artifacts_dir or (workdir / "artifacts")
        artifacts = ArtifactExtractor.extract_and_persist(workdir, persist_dir)

        return {
            "passed": return_code == 0 and not timed_out,
            "exit_code": return_code,
            "timed_out": timed_out,
            "command": list(command),
            "cwd": str(workdir),
            "stdout": output,
            "stderr": error_output,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "backend": "local",
            "repo_commit": get_current_git_commit(),
            "artifacts": artifacts,
        }

    @staticmethod
    def _validate_arguments(command: list[str], framework: str) -> None:
        """Reject interpreter escape hatches while keeping normal test runners usable."""
        lowered = [item.lower() for item in command[1:]]
        dangerous = {"-c", "--command", "-e", "--eval", "-i", "--interactive"}
        if dangerous.intersection(lowered):
            raise ValueError("Inline interpreter execution is not allowed")
        cmd_name = command[0].lower().split("\\")[-1]
        if cmd_name in {"python", "python.exe", "py", "py.exe"}:
            for index, item in enumerate(lowered):
                if item in {"-m", "--module"}:
                    module = lowered[index + 1] if index + 1 < len(lowered) else ""
                    if module not in {"pytest", "unittest"}:
                        raise ValueError(f"Python module is not allowed: {module}")
        if any(item in {"&&", "||", ";", "|", ">", "<"} for item in command):
            raise ValueError("Shell operators are not allowed")


class DockerSandboxExecutor(BaseTestExecutor):
    """Run tests inside an isolated, resource-constrained Docker container with guaranteed lifecycle."""

    FRAMEWORK_IMAGES = {
        "pytest": "python:3.11-slim",
        "jest": "node:18-slim",
        "playwright": "mcr.microsoft.com/playwright:v1.40.0-focal",
        "maven": "maven:3.9-eclipse-temurin-17",
    }

    PINNED_RUNNER_IMAGES = {
        "pytest": "testteller-runner-python:3.11-v1",
        "jest": "testteller-runner-node:18-v1",
    }

    def __init__(
        self,
        workspace_root: str | Path,
        timeout_seconds: int = 120,
        max_output_chars: int = 30_000,
        image: str | None = None,
        memory_limit: str = "512m",
        cpus_limit: str = "1.0",
        pids_limit: int = 100,
        allow_network: bool = False,
        container_workspace: str = "/workspace",
        policy: SandboxPolicy | None = None,
        task_id: str | None = None,
        use_pinned_runner: bool = True,
        persistent_artifacts_dir: str | Path | None = None,
        runner_func: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        super().__init__(
            workspace_root=workspace_root,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            persistent_artifacts_dir=persistent_artifacts_dir,
        )
        self.image = image
        self.task_id = task_id
        self.use_pinned_runner = use_pinned_runner
        self._runner_func = runner_func

        if policy is not None:
            self.policy = policy
        else:
            net_policy = NetworkPolicy.BRIDGE if allow_network else NetworkPolicy.NONE
            self.policy = SandboxPolicy(
                memory_limit=memory_limit,
                cpus_limit=cpus_limit,
                pids_limit=pids_limit,
                timeout_seconds=timeout_seconds,
                network_policy=net_policy,
                container_workspace=container_workspace,
                runner_image=image,
            )

        # Backward compatibility properties
        self.memory_limit = self.policy.memory_limit
        self.cpus_limit = self.policy.cpus_limit
        self.pids_limit = self.policy.pids_limit
        self.allow_network = (self.policy.network_policy == NetworkPolicy.BRIDGE)
        self.container_workspace = self.policy.container_workspace

    def resolve_image(self, framework: str = "pytest") -> str:
        """Resolve runner image prioritizing pinned runner images for deterministic execution."""
        fw = framework.lower()
        if self.image:
            return self.image
        if self.policy.runner_image:
            return self.policy.runner_image
        if self.use_pinned_runner:
            return self.PINNED_RUNNER_IMAGES.get(fw, self.FRAMEWORK_IMAGES.get(fw, "python:3.11-slim"))
        return self.FRAMEWORK_IMAGES.get(fw, "python:3.11-slim")

    def build_docker_command(
        self,
        command: Sequence[str],
        workdir: Path,
        framework: str = "pytest",
    ) -> list[str]:
        """Construct legacy/standalone docker run command for backward compatibility."""
        target_image = self.resolve_image(framework)
        host_path = str(workdir.resolve()).replace("\\", "/")
        container_cmd = self._normalize_container_command(list(command), framework)

        docker_args = [
            "docker",
            "run",
            "--rm",
            f"--memory={self.policy.memory_limit}",
            f"--cpus={self.policy.cpus_limit}",
            f"--pids-limit={self.policy.pids_limit}",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            f"--network={'bridge' if self.allow_network else 'none'}",
            "-v",
            f"{host_path}:{self.container_workspace}:rw",
            "-w",
            self.container_workspace,
            target_image,
            *container_cmd,
        ]
        return docker_args

    def run(
        self,
        command: Sequence[str],
        cwd: str | Path | None = None,
        framework: str = "pytest",
    ) -> dict[str, Any]:
        if not command:
            raise ValueError("Test command cannot be empty")
        workdir = (Path(cwd) if cwd else self.workspace_root).resolve()
        self._ensure_inside(workdir)

        target_image = self.resolve_image(framework)
        augmented_cmd = ensure_reporting_command(command, framework=framework, include_json_report=True)
        container_cmd = self._normalize_container_command(augmented_cmd, framework)
        persist_dir = self.persistent_artifacts_dir or (workdir / "artifacts")

        # Stage workspace if workspace isolation is enabled
        if self.policy.isolate_workspace:
            with PerRunWorkspace(source_workspace=workdir, task_id=self.task_id) as staged_ws:
                assert staged_ws.staging_dir is not None
                lifecycle = ContainerLifecycleManager(
                    policy=self.policy,
                    task_id=self.task_id,
                    runner_func=self._runner_func,
                )
                res = lifecycle.run_container(
                    image=target_image,
                    command=container_cmd,
                    host_workspace=staged_ws.staging_dir,
                )
                # Persist artifacts before staging directory is wiped!
                artifacts = ArtifactExtractor.extract_and_persist(staged_ws.staging_dir, persist_dir)
                runner_digest = lifecycle.get_image_digest(target_image)
        else:
            lifecycle = ContainerLifecycleManager(
                policy=self.policy,
                task_id=self.task_id,
                runner_func=self._runner_func,
            )
            res = lifecycle.run_container(
                image=target_image,
                command=container_cmd,
                host_workspace=workdir,
            )
            artifacts = ArtifactExtractor.extract_and_persist(workdir, persist_dir)
            runner_digest = lifecycle.get_image_digest(target_image)

        exit_code = res.get("exit_code")
        timed_out = res.get("timed_out", False)
        output = (res.get("stdout") or "")[-self.max_output_chars :]
        error_output = (res.get("stderr") or "")[-self.max_output_chars :]

        return {
            "passed": exit_code == 0 and not timed_out,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "command": list(command),
            "cwd": str(workdir),
            "stdout": output,
            "stderr": error_output,
            "duration_ms": res.get("duration_ms", 0.0),
            "backend": "docker",
            "runner_image": target_image,
            "runner_digest": runner_digest,
            "runner_version": self.policy.runner_version,
            "repo_commit": get_current_git_commit(),
            "container_name": res.get("container_name"),
            "artifacts": artifacts,
            "policy": self.policy.to_dict(),
        }

    @staticmethod
    def _normalize_container_command(command: list[str], framework: str) -> list[str]:
        """Convert host-specific binary paths (e.g. D:\\python.exe) to container-safe binaries."""
        first = Path(command[0]).name.lower()
        if first.endswith(".exe") or first.endswith(".cmd"):
            first = first.rsplit(".", 1)[0]
        if first in ("python", "py"):
            first = "python"
        elif first in ("node", "npm", "npx"):
            first = first
        elif first == "pytest":
            first = "pytest"

        return [first, *command[1:]]


def is_docker_available() -> bool:
    """Check if Docker CLI is installed and the Docker daemon is running."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=3,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def create_test_executor(
    workspace_root: str | Path,
    backend: str = "auto",
    timeout_seconds: int = 120,
    max_output_chars: int = 30_000,
    policy: SandboxPolicy | None = None,
    task_id: str | None = None,
    persistent_artifacts_dir: str | Path | None = None,
    **kwargs: Any,
) -> BaseTestExecutor:
    """Factory function for creating appropriate test executor instance."""
    backend_mode = (backend or "auto").lower()

    if backend_mode == "docker":
        if not is_docker_available():
            raise RuntimeError(
                "Docker sandbox executor requested, but Docker is not installed or the Docker daemon is not running."
            )
        return DockerSandboxExecutor(
            workspace_root=workspace_root,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            policy=policy,
            task_id=task_id,
            persistent_artifacts_dir=persistent_artifacts_dir,
            **kwargs,
        )

    if backend_mode == "auto":
        if is_docker_available():
            logger.info("Docker daemon available. Using DockerSandboxExecutor.")
            return DockerSandboxExecutor(
                workspace_root=workspace_root,
                timeout_seconds=timeout_seconds,
                max_output_chars=max_output_chars,
                policy=policy,
                task_id=task_id,
                persistent_artifacts_dir=persistent_artifacts_dir,
                **kwargs,
            )
        logger.warning("Docker is not available. Falling back to LocalSubprocessExecutor.")
        return LocalSubprocessExecutor(
            workspace_root=workspace_root,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            persistent_artifacts_dir=persistent_artifacts_dir,
        )

    return LocalSubprocessExecutor(
        workspace_root=workspace_root,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
        persistent_artifacts_dir=persistent_artifacts_dir,
    )


# Backward compatibility alias
SafeTestExecutor = LocalSubprocessExecutor
