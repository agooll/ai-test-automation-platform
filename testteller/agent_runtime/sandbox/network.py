"""Management of isolated, internal Docker networks for target-only test execution."""

from __future__ import annotations

import logging
import subprocess
from typing import Callable, Sequence
import uuid

logger = logging.getLogger(__name__)


class IsolatedTargetNetwork:
    """Manages an internal, isolated Docker network connecting only the target-app and the test runner."""

    def __init__(
        self,
        network_name: str | None = None,
        runner_func: Callable[..., subprocess.CompletedProcess] | None = None,
        timeout: int = 15,
    ) -> None:
        self.network_name = network_name or f"testteller_internal_{uuid.uuid4().hex[:8]}"
        self.timeout = timeout
        self._runner = runner_func or subprocess.run
        self._target_containers: list[str] = []
        self._network_created = False

    def __enter__(self) -> IsolatedTargetNetwork:
        self.create_network()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    def create_network(self) -> str:
        """Create an internal, unrouted Docker network (--internal)."""
        cmd = ["docker", "network", "create", "--internal", self.network_name]
        res = self._runner(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
        if res.returncode == 0:
            self._network_created = True
            logger.debug("Created internal network %s", self.network_name)
        else:
            logger.debug("Could not create internal network %s: %s", self.network_name, res.stderr)
        return self.network_name

    def attach_target_container(
        self,
        image: str,
        container_name: str | None = None,
        command: Sequence[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Launch and attach a target application container to the isolated network."""
        name = container_name or f"target_app_{uuid.uuid4().hex[:8]}"
        cmd = [
            "docker", "run", "-d",
            "--name", name,
            "--network", self.network_name,
            "--network-alias", "target-app",
            "--network-alias", "target",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--pids-limit=100",
        ]
        if env:
            for k, v in env.items():
                cmd.extend(["-e", f"{k}={v}"])
        cmd.append(image)
        if command:
            cmd.extend(command)

        res = self._runner(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
        if res.returncode == 0:
            self._target_containers.append(name)
            logger.debug("Attached target container %s to network %s", name, self.network_name)
            return name
        else:
            raise RuntimeError(f"Failed to start target container {name}: {res.stderr}")

    def cleanup(self) -> None:
        """Stop and remove all target containers and destroy the internal network."""
        for c_name in list(self._target_containers):
            try:
                self._runner(["docker", "rm", "-f", c_name], capture_output=True, text=True, timeout=self.timeout, check=False)
            except Exception as exc:
                logger.debug("Error stopping target container %s: %s", c_name, exc)
        self._target_containers.clear()

        if self._network_created:
            try:
                self._runner(["docker", "network", "rm", self.network_name], capture_output=True, text=True, timeout=self.timeout, check=False)
                logger.debug("Removed internal network %s", self.network_name)
            except Exception as exc:
                logger.debug("Error removing network %s: %s", self.network_name, exc)
            self._network_created = False
