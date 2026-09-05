"""Safe, bounded execution of generated test projects."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence


class SafeTestExecutor:
    """Run only approved test commands inside a designated workspace."""

    DEFAULT_ALLOWED = {
        "pytest": {"pytest", "python", "py"},
        "jest": {"jest", "npx", "npm", "node"},
        "playwright": {"pytest", "npx", "playwright"},
        "maven": {"mvn", "mvnw", "mvnw.cmd"},
    }

    def __init__(self, workspace_root: str | Path, timeout_seconds: int = 120,
                 max_output_chars: int = 30_000) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def run(self, command: Sequence[str], cwd: str | Path | None = None,
            framework: str = "pytest") -> dict[str, Any]:
        if not command:
            raise ValueError("Test command cannot be empty")
        workdir = (Path(cwd) if cwd else self.workspace_root).resolve()
        self._ensure_inside(workdir)
        executable = Path(str(command[0])).name.lower()
        allowed = {item.lower() for item in self.DEFAULT_ALLOWED.get(framework.lower(), set())}
        if executable not in allowed:
            raise ValueError(f"Command is not allowed for {framework}: {command[0]}")
        self._validate_arguments([str(item) for item in command], framework.lower())

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [str(item) for item in command], cwd=workdir, env=env,
                capture_output=True, text=True, timeout=self.timeout_seconds,
                shell=False, check=False,
            )
            timed_out = False
            return_code = completed.returncode
            stdout, stderr = completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            return_code = None
            stdout = self._text(exc.stdout)
            stderr = self._text(exc.stderr) + "\n[timeout]"

        output = (stdout or "")[-self.max_output_chars:]
        error_output = (stderr or "")[-self.max_output_chars:]
        return {
            "passed": return_code == 0 and not timed_out,
            "exit_code": return_code,
            "timed_out": timed_out,
            "command": list(command),
            "cwd": str(workdir),
            "stdout": output,
            "stderr": error_output,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

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

    @staticmethod
    def _validate_arguments(command: list[str], framework: str) -> None:
        """Reject interpreter escape hatches while keeping normal test runners usable."""
        lowered = [item.lower() for item in command[1:]]
        dangerous = {"-c", "--command", "-e", "--eval", "-i", "--interactive"}
        if dangerous.intersection(lowered):
            raise ValueError("Inline interpreter execution is not allowed")
        if command[0].lower().split("\\")[-1] in {"python", "python.exe", "py", "py.exe"}:
            for index, item in enumerate(lowered):
                if item in {"-m", "--module"}:
                    module = lowered[index + 1] if index + 1 < len(lowered) else ""
                    if module not in {"pytest", "unittest"}:
                        raise ValueError(f"Python module is not allowed: {module}")
        if any(item in {"&&", "||", ";", "|", ">", "<"} for item in command):
            raise ValueError("Shell operators are not allowed")
