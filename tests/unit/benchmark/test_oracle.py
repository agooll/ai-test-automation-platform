from pathlib import Path
from unittest.mock import MagicMock
import pytest

from testteller.benchmark.oracle import DualOracleEvaluator, apply_patch_to_dir
from testteller.benchmark.schema import MutantSpec


def test_apply_patch_python(tmp_path: Path):
    target_file = tmp_path / "sample.py"
    target_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    patch_file = tmp_path / "mutant.patch"
    patch_file.write_text(
        "--- a/sample.py\n+++ b/sample.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a + b\n+    return a - b\n",
        encoding="utf-8",
    )

    success = apply_patch_to_dir(patch_file, tmp_path)
    assert success is True
    assert "return a - b" in target_file.read_text(encoding="utf-8")


def test_dual_oracle_evaluation_detects_mutant(tmp_path: Path):
    # Setup mock executors
    clean_executor = MagicMock()
    clean_executor.run.return_value = {"exit_code": 0, "stdout": "1 passed", "stderr": "", "passed": True}

    mutant_executor = MagicMock()
    # Mutant execution fails (AssertionError) -> detected!
    mutant_executor.run.return_value = {"exit_code": 1, "stdout": "FAILED - AssertionError", "stderr": "", "passed": False}

    executors = [clean_executor, mutant_executor]

    def mock_factory(framework, ws):
        return executors.pop(0)

    evaluator = DualOracleEvaluator(executor_factory=mock_factory)

    patch_file = tmp_path / "mut.patch"
    patch_file.write_text("--- a/code.py\n+++ b/code.py\n", encoding="utf-8")
    mutants = [MutantSpec("mut-01", "Test defect", str(patch_file))]

    clean_passed, mut_results, semantic_success = evaluator.evaluate(
        clean_workspace_dir=tmp_path,
        test_framework="pytest",
        mutants=mutants,
        base_dir=tmp_path,
    )

    assert clean_passed is True
    assert len(mut_results) == 1
    assert mut_results[0].detected is True
    assert semantic_success is True


def test_dual_oracle_evaluation_flags_vacuous_test(tmp_path: Path):
    # If the test passes on clean code AND passes on mutated code, the mutant was NOT detected!
    clean_executor = MagicMock()
    clean_executor.run.return_value = {"exit_code": 0, "stdout": "1 passed", "stderr": "", "passed": True}

    mutant_executor = MagicMock()
    # Mutant execution still passes -> mutant survived!
    mutant_executor.run.return_value = {"exit_code": 0, "stdout": "1 passed (vacuous)", "stderr": "", "passed": True}

    executors = [clean_executor, mutant_executor]

    def mock_factory(framework, ws):
        return executors.pop(0)

    evaluator = DualOracleEvaluator(executor_factory=mock_factory)

    patch_file = tmp_path / "mut.patch"
    patch_file.write_text("--- a/code.py\n+++ b/code.py\n", encoding="utf-8")
    mutants = [MutantSpec("mut-01", "Test defect", str(patch_file))]

    clean_passed, mut_results, semantic_success = evaluator.evaluate(
        clean_workspace_dir=tmp_path,
        test_framework="pytest",
        mutants=mutants,
        base_dir=tmp_path,
    )

    assert clean_passed is True
    assert len(mut_results) == 1
    assert mut_results[0].detected is False  # Mutant was NOT caught!
    assert semantic_success is False  # Fails semantic oracle!


def test_dual_oracle_evaluation_targets_only_generated_test_files(tmp_path: Path):
    clean_executor = MagicMock()
    clean_executor.run.return_value = {"exit_code": 0, "stdout": "1 passed", "stderr": "", "passed": True}

    mutant_executor = MagicMock()
    mutant_executor.run.return_value = {"exit_code": 1, "stdout": "FAILED", "stderr": "", "passed": False}

    executors = [clean_executor, mutant_executor]
    evaluator = DualOracleEvaluator(executor_factory=lambda fw, ws: executors.pop(0))

    patch_file = tmp_path / "mut.patch"
    patch_file.write_text("--- a/code.py\n+++ b/code.py\n", encoding="utf-8")
    mutants = [MutantSpec("mut-01", "Defect", str(patch_file))]

    # Case 1: Pass generated test files
    gen_file = tmp_path / "tests" / "test_generated.py"
    clean_passed, mut_results, sem_success = evaluator.evaluate(
        clean_workspace_dir=tmp_path,
        test_framework="pytest",
        mutants=mutants,
        base_dir=tmp_path,
        generated_test_files=[str(gen_file)],
    )

    assert clean_passed is True
    assert sem_success is True
    # Verify commands passed to executors targeted ONLY the generated file
    clean_cmd = clean_executor.run.call_args[1]["command"]
    assert clean_cmd == ["pytest", "-v", "tests/test_generated.py"]

    # Case 2: Empty generated test files fails immediately
    evaluator_empty = DualOracleEvaluator(executor_factory=lambda fw, ws: MagicMock())
    c_pass, m_res, s_succ = evaluator_empty.evaluate(
        clean_workspace_dir=tmp_path,
        test_framework="pytest",
        mutants=mutants,
        base_dir=tmp_path,
        generated_test_files=[],
    )
    assert c_pass is False
    assert s_succ is False

