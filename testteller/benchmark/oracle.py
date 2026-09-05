"""Dual-Oracle Semantic Evaluation for generated test quality and defect detection."""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable

from testteller.agent_runtime.tools.execution import BaseTestExecutor, create_test_executor
from testteller.benchmark.schema import MutantEvaluationResult, MutantSpec

logger = logging.getLogger(__name__)


def apply_patch_to_dir(patch_file: Path, target_dir: Path) -> bool:
    """Apply a unified diff patch to a target directory.

    Tries `git apply` first, then falls back to a built-in Python hunk applier.
    """
    if not patch_file.exists():
        raise FileNotFoundError(f"Patch file not found: {patch_file}")

    patch_content = patch_file.read_text(encoding="utf-8")

    # 1. Try git apply if git is available
    try:
        proc = subprocess.run(
            ["git", "apply", "--ignore-whitespace", str(patch_file)],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return True
    except Exception as e:
        logger.debug("git apply failed or not available, falling back to python applier: %s", e)

    # 2. Pure Python fallback patch applier
    return _apply_patch_python(patch_content, target_dir)


def _apply_patch_python(patch_content: str, target_dir: Path) -> bool:
    """Lightweight pure-Python unified diff applier for single/multi-file patches."""
    lines = patch_content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            orig_header = line
            i += 1
            if i < len(lines) and lines[i].startswith("+++ "):
                new_header = lines[i]
                # Determine relative file path, stripping a/ or b/ prefixes
                raw_path = new_header[4:].strip()
                if raw_path.startswith("b/") or raw_path.startswith("a/"):
                    raw_path = raw_path[2:]
                target_file = target_dir / raw_path
                i += 1

                if not target_file.exists():
                    logger.warning("Target file to patch does not exist: %s", target_file)
                    continue

                file_lines = target_file.read_text(encoding="utf-8").splitlines()
                # Parse hunks for this file
                hunks = []
                while i < len(lines) and lines[i].startswith("@@"):
                    hunk_header = lines[i]
                    i += 1
                    hunk_lines = []
                    while i < len(lines) and not lines[i].startswith("--- ") and not lines[i].startswith("@@"):
                        hunk_lines.append(lines[i])
                        i += 1
                    hunks.append((hunk_header, hunk_lines))

                # Apply hunks to file_lines
                patched_lines = _apply_hunks_to_lines(file_lines, hunks)
                target_file.write_text("\n".join(patched_lines) + "\n", encoding="utf-8")
                continue
        i += 1
    return True


def _apply_hunks_to_lines(original_lines: list[str], hunks: list[tuple[str, list[str]]]) -> list[str]:
    """Apply hunks sequentially, using hunk header line numbers to disambiguate identical code."""
    result = list(original_lines)
    for header, hunk_lines in hunks:
        # Parse target starting line number from hunk header: @@ -start,len +start,len @@
        target_idx = 0
        m = re.search(r"@@\s*-(\d+)", header)
        if m:
            try:
                target_idx = max(0, int(m.group(1)) - 1)
            except Exception:
                target_idx = 0

        # Extract lines to find and lines to replace
        old_lines = []
        new_lines = []
        for hl in hunk_lines:
            if hl.startswith("-"):
                old_lines.append(hl[1:])
            elif hl.startswith("+"):
                new_lines.append(hl[1:])
            elif hl.startswith(" "):
                old_lines.append(hl[1:])
                new_lines.append(hl[1:])

        # Find occurrence of old_lines in result
        old_len = len(old_lines)
        if old_len == 0:
            continue

        # Sort candidate positions by proximity to target line from hunk header
        candidate_indices = sorted(
            range(len(result) - old_len + 1),
            key=lambda idx: abs(idx - target_idx),
        )

        found_idx = -1
        for j in candidate_indices:
            if result[j : j + old_len] == old_lines:
                found_idx = j
                break

        if found_idx == -1:
            # Flexible whitespace search fallback
            old_stripped = [l.strip() for l in old_lines]
            for j in candidate_indices:
                if [l.strip() for l in result[j : j + old_len]] == old_stripped:
                    found_idx = j
                    break

        if found_idx != -1:
            result = result[:found_idx] + new_lines + result[found_idx + old_len :]
        else:
            logger.warning("Could not apply hunk: %s", header)

    return result


class DualOracleEvaluator:
    """Evaluates generated tests against clean code (PASS Oracle) and mutant code (FAIL Oracle)."""

    def __init__(
        self,
        executor_factory: Callable[[str, Path], BaseTestExecutor] | None = None,
        execution_backend: str = "docker",
    ):
        self.executor_factory = executor_factory or (
            lambda framework, ws: create_test_executor(
                workspace_root=ws,
                backend=execution_backend,
            )
        )
        self.execution_backend = execution_backend

    def evaluate(
        self,
        clean_workspace_dir: Path,
        test_framework: str,
        mutants: list[MutantSpec],
        base_dir: Path,
        generated_test_files: Sequence[str] | None = None,
        test_command: list[str] | None = None,
        timeout_sec: int = 60,
    ) -> tuple[bool, list[MutantEvaluationResult], bool]:
        """Perform dual-oracle evaluation on ONLY the generated test files.

        Returns:
            (clean_exec_passed, mutant_results, semantic_success)
        """
        # Resolve target test files generated in this run
        target_files: list[str] = []
        if generated_test_files:
            for tf in generated_test_files:
                p = Path(tf)
                # If absolute path, make relative to clean_workspace_dir
                try:
                    rel = p.relative_to(clean_workspace_dir)
                    target_files.append(str(rel).replace("\\", "/"))
                except ValueError:
                    # Already relative or just a filename
                    target_files.append(str(tf).replace("\\", "/"))

        # If no tests were generated, the run cannot pass semantic evaluation
        if not target_files and generated_test_files is not None:
            logger.warning("DualOracle: No generated test files provided; evaluation fails.")
            return False, [], False

        if test_command:
            command = list(test_command)
        else:
            base_cmd = ["pytest", "-v"] if test_framework == "pytest" else ["npm", "test"]
            if target_files:
                command = base_cmd + target_files
            else:
                command = base_cmd

        # 1. Oracle 1: Clean codebase must PASS
        clean_executor = self.executor_factory(test_framework, clean_workspace_dir)
        clean_res = clean_executor.run(command=command, framework=test_framework)
        clean_passed = bool(clean_res.get("passed", False))

        mutant_results: list[MutantEvaluationResult] = []

        # 2. Oracle 2: Seeded mutants must FAIL (detected by the generated tests)
        for mutant in mutants:
            patch_path = Path(mutant.patch_path)
            if not patch_path.is_absolute():
                patch_path = (base_dir / patch_path).resolve()

            with tempfile.TemporaryDirectory(prefix=f"eval_mut_{mutant.mutant_id}_") as temp_dir:
                mutated_dir = Path(temp_dir) / "workspace"
                shutil.copytree(clean_workspace_dir, mutated_dir)

                # Apply mutant patch
                apply_patch_to_dir(patch_path, mutated_dir)

                # Run tests against mutated code
                mutant_executor = self.executor_factory(test_framework, mutated_dir)
                res = mutant_executor.run(command=command, framework=test_framework)

                # Mutant is detected (killed) if tests FAIL
                detected = not bool(res.get("passed", False))
                if mutant.expected_failed_test_pattern and detected:
                    combined_out = f"{res.get('stdout', '')} {res.get('stderr', '')}"
                    detected = mutant.expected_failed_test_pattern in combined_out

                mutant_results.append(
                    MutantEvaluationResult(
                        mutant_id=mutant.mutant_id,
                        detected=detected,
                        exit_code=int(res.get("exit_code", 1)),
                        output_snippet=(res.get("stdout", "")[:200] if not res.get("passed", False) else ""),
                    )
                )

        # 3. Semantic Success requires clean PASS AND (all mutants detected or no mutants)
        if not mutants:
            semantic_success = clean_passed
        else:
            all_detected = all(m.detected for m in mutant_results)
            semantic_success = clean_passed and all_detected

        return clean_passed, mutant_results, semantic_success
