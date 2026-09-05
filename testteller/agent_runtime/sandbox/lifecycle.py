"""Deterministic container lifecycle management with guaranteed timeout cleanup."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Sequence
import uuid

from .policy import NetworkPolicy, SandboxPolicy

logger = logging.getLogger(__name__)


class ContainerLifecycleManager:
    """Manages the explicit 5-stage lifecycle of a sandbox container:

    create -> start -> wait(timeout/kill) -> logs -> (finally) rm -f
    """

    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        task_id: str | None = None,
        runner_func: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.policy = policy or SandboxPolicy()
        self.task_id = task_id or uuid.uuid4().hex[:8]
        self.container_name = f"testteller_{self.task_id}_{uuid.uuid4().hex[:8]}"
        self._runner = runner_func or subprocess.run

    def build_create_args(
        self,
        image: str,
        command: Sequence[str],
        host_workspace: Path,
    ) -> list[str]:
        """Construct deterministic docker create arguments with full security confinement."""
        host_path = str(host_workspace.resolve()).replace("\\", "/")
        net_val = (
            self.policy.network_policy.value
            if isinstance(self.policy.network_policy, NetworkPolicy)
            else str(self.policy.network_policy)
        )

        args = [
            "docker",
            "create",
            "--name",
            self.container_name,
            f"--memory={self.policy.memory_limit}",
            f"--cpus={self.policy.cpus_limit}",
            f"--pids-limit={self.policy.pids_limit}",
        ]

        if self.policy.no_new_privileges:
            args.append("--security-opt=no-new-privileges")
        if self.policy.cap_drop_all:
            args.append("--cap-drop=ALL")
        if self.policy.read_only_rootfs:
            args.append("--read-only")

        for tmpfs_path, tmpfs_opts in self.policy.tmpfs_mounts.items():
            args.extend(["--tmpfs", f"{tmpfs_path}:{tmpfs_opts}"])

        if self.policy.network_policy == NetworkPolicy.TARGET_ONLY:
            target_net = self.policy.target_network or "bridge"
            args.append(f"--network={target_net}")
            if self.policy.target_host:
                args.extend(["--add-host", f"target:{self.policy.target_host}"])
        else:
            args.append(f"--network={net_val}")

        # Secrets isolation: deny-by-default environment variables
        env_vars = self.policy.build_env()
        for env_key, env_val in env_vars.items():
            args.extend(["-e", f"{env_key}={env_val}"])

        # Volume and working directory
        args.extend([
            "-v",
            f"{host_path}:{self.policy.container_workspace}:rw",
            "-w",
            self.policy.container_workspace,
        ])

        if self.policy.user:
            args.extend(["--user", self.policy.user])

        args.append(image)
        args.extend(command)
        return args

    def run_container(
        self,
        image: str,
        command: Sequence[str],
        host_workspace: Path,
    ) -> dict[str, Any]:
        """Execute container through strict lifecycle stages with guaranteed cleanup."""
        create_args = self.build_create_args(image, command, host_workspace)
        started_at = time.perf_counter()

        logger.debug("Creating sandbox container %s: %s", self.container_name, " ".join(create_args))
        try:
            create_res = self._runner(create_args, capture_output=True, text=True, check=False)
        except subprocess.TimeoutExpired:
            return {
                "exit_code": None,
                "timed_out": True,
                "stdout": "",
                "stderr": f"\n[timeout: container killed after {self.policy.timeout_seconds}s]",
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "container_name": self.container_name,
            }

        if create_res.returncode != 0:
            return {
                "exit_code": create_res.returncode,
                "timed_out": False,
                "stdout": create_res.stdout or "",
                "stderr": f"Failed to create container: {create_res.stderr or ''}",
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "container_name": self.container_name,
            }

        timed_out = False
        exit_code: int | None = None
        stdout = ""
        stderr = ""

        try:
            # Stage 2: Start
            self._runner(
                ["docker", "start", self.container_name],
                capture_output=True,
                text=True,
                check=False,
            )

            # Stage 3: Wait with timeout
            try:
                wait_res = self._runner(
                    ["docker", "wait", self.container_name],
                    capture_output=True,
                    text=True,
                    timeout=self.policy.timeout_seconds,
                    check=False,
                )
                raw_exit = (wait_res.stdout or "").strip()
                exit_code = int(raw_exit) if raw_exit.isdigit() else wait_res.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                logger.warning("Sandbox container %s timed out after %ss, killing...", self.container_name, self.policy.timeout_seconds)
                try:
                    self._runner(
                        ["docker", "kill", self.container_name],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                except Exception:
                    pass

            # Stage 4: Logs
            try:
                logs_res = self._runner(
                    ["docker", "logs", self.container_name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                stdout = logs_res.stdout or ""
                stderr = logs_res.stderr or ""
            except Exception:
                pass

            if timed_out:
                stderr += f"\n[timeout: container killed after {self.policy.timeout_seconds}s]"

        finally:
            # Stage 5: Guaranteed Cleanup (No Orphan Containers)
            logger.debug("Force-removing sandbox container %s", self.container_name)
            try:
                self._runner(
                    ["docker", "rm", "-f", self.container_name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except Exception as exc:
                logger.debug("Non-fatal exception during container cleanup %s: %s", self.container_name, exc)

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        return {
            "exit_code": exit_code if not timed_out else None,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "container_name": self.container_name,
        }
