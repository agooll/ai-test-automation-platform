"""Sandbox execution policies and security configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
from typing import Any


class NetworkPolicy(str, Enum):
    """Network egress policy for test execution containers."""

    NONE = "none"
    BRIDGE = "bridge"
    HOST = "host"
    TARGET_ONLY = "target_only"


@dataclass
class SandboxPolicy:
    """Hard security, resource, and isolation configuration for Docker Sandbox."""

    memory_limit: str = "512m"
    cpus_limit: str = "1.0"
    pids_limit: int = 100
    timeout_seconds: int = 120
    operation_timeout: int = 15
    network_policy: NetworkPolicy = NetworkPolicy.NONE
    target_host: str | None = None
    target_network: str | None = None
    target_internal: bool = True
    read_only_rootfs: bool = True
    tmpfs_mounts: dict[str, str] = field(
        default_factory=lambda: {
            "/tmp": "rw,noexec,nosuid,size=64m",
            "/run": "rw,noexec,nosuid,size=16m",
        }
    )
    user: str = "1000:1000"
    cap_drop_all: bool = True
    no_new_privileges: bool = True
    allowed_env_vars: list[str] = field(default_factory=list)
    default_env_vars: dict[str, str] = field(
        default_factory=lambda: {
            "PYTHONUNBUFFERED": "1",
            "TESTTELLER_SANDBOX": "1",
            "CI": "1",
        }
    )
    isolate_workspace: bool = True
    container_workspace: str = "/workspace"
    runner_image: str | None = None
    runner_version: str = "3.11-v1"

    def build_env(self) -> dict[str, str]:
        """Construct sanitized environment variables adhering to Secrets Isolation (deny-by-default)."""
        clean_env = dict(self.default_env_vars)
        for key in self.allowed_env_vars:
            val = os.environ.get(key)
            if val is not None:
                clean_env[key] = val
        return clean_env

    def to_dict(self) -> dict[str, Any]:
        """Return serialized representation without exposing any secret values."""
        return {
            "memory_limit": self.memory_limit,
            "cpus_limit": self.cpus_limit,
            "pids_limit": self.pids_limit,
            "timeout_seconds": self.timeout_seconds,
            "operation_timeout": self.operation_timeout,
            "network_policy": self.network_policy.value if isinstance(self.network_policy, NetworkPolicy) else str(self.network_policy),
            "target_host": self.target_host,
            "target_network": self.target_network,
            "target_internal": self.target_internal,
            "read_only_rootfs": self.read_only_rootfs,
            "tmpfs_mounts": self.tmpfs_mounts,
            "user": self.user,
            "cap_drop_all": self.cap_drop_all,
            "no_new_privileges": self.no_new_privileges,
            "allowed_env_vars": list(self.allowed_env_vars),
            "isolate_workspace": self.isolate_workspace,
            "runner_version": self.runner_version,
        }
