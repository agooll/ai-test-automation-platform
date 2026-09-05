#!/usr/bin/env python3
"""Build script for TestTeller standard and pinned test runner Docker images."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_runners")


def build_image(image_tag: str, dockerfile: Path, context_dir: Path) -> bool:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        logger.error("Docker CLI is not installed or not in PATH.")
        return False

    cmd = [
        "docker",
        "build",
        "-t",
        image_tag,
        "-f",
        str(dockerfile),
        str(context_dir),
    ]
    logger.info("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, check=False)
        if proc.returncode == 0:
            logger.info("Successfully built %s", image_tag)
            return True
        logger.error("Failed building %s (exit code %d)", image_tag, proc.returncode)
        return False
    except Exception as exc:
        logger.error("Exception while building %s: %s", image_tag, exc)
        return False


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    docker_dir = repo_root / "docker"

    py_dockerfile = docker_dir / "runner.python.Dockerfile"
    node_dockerfile = docker_dir / "runner.node.Dockerfile"

    success_py = build_image("testteller-runner-python:3.11-v1", py_dockerfile, docker_dir)
    success_node = build_image("testteller-runner-node:18-v1", node_dockerfile, docker_dir)

    if success_py and success_node:
        logger.info("All runner images built successfully.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
