"""Per-run workspace isolation preventing mutation or pollution of host directories."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import tempfile
import uuid

logger = logging.getLogger(__name__)

DEFAULT_IGNORE_PATTERNS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".idea",
    ".vscode",
    "*.pyc",
    "*.sqlite",
    "*.sqlite-journal",
}


class PerRunWorkspace:
    """Isolates a test execution workspace into a temporary staging directory."""

    def __init__(
        self,
        source_workspace: str | Path,
        task_id: str | None = None,
        base_temp_dir: str | Path | None = None,
        ignore_patterns: set[str] | None = None,
    ) -> None:
        self.source_workspace = Path(source_workspace).resolve()
        self.task_id = task_id or uuid.uuid4().hex[:8]
        self.base_temp_dir = Path(base_temp_dir).resolve() if base_temp_dir else None
        self.ignore_patterns = ignore_patterns or DEFAULT_IGNORE_PATTERNS
        self.staging_dir: Path | None = None

    def __enter__(self) -> PerRunWorkspace:
        return self.create()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    def create(self) -> PerRunWorkspace:
        """Create staging directory and copy workspace contents safely."""
        prefix = f"testteller_sandbox_{self.task_id}_"
        temp_dir = tempfile.mkdtemp(prefix=prefix, dir=self.base_temp_dir)
        self.staging_dir = Path(temp_dir).resolve()

        if self.source_workspace.exists() and self.source_workspace.is_dir():
            def _ignore_filter(directory: str, contents: list[str]) -> set[str]:
                ignored = set()
                for item in contents:
                    for pattern in self.ignore_patterns:
                        if pattern.startswith("*") and item.endswith(pattern[1:]):
                            ignored.add(item)
                        elif item == pattern:
                            ignored.add(item)
                return ignored

            # Copy contents from source_workspace into self.staging_dir
            for item in self.source_workspace.iterdir():
                dest = self.staging_dir / item.name
                if item.name in self.ignore_patterns:
                    continue
                if item.is_dir():
                    shutil.copytree(item, dest, ignore=_ignore_filter, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

        logger.debug("Created isolated staging workspace at %s", self.staging_dir)
        return self

    def cleanup(self) -> None:
        """Destroy staging directory and free all temporary resources."""
        if self.staging_dir and self.staging_dir.exists():
            try:
                shutil.rmtree(self.staging_dir, ignore_errors=True)
                logger.debug("Cleaned up staging workspace at %s", self.staging_dir)
            except Exception as exc:
                logger.warning("Failed to clean up staging workspace %s: %s", self.staging_dir, exc)
            finally:
                self.staging_dir = None
