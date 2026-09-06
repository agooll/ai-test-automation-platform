"""Deterministic code-level rules for AST anti-counterfeit analysis."""

from __future__ import annotations

import ast
import re
from typing import List, Optional

from .code_models import CodeViolation, CodeViolationCode
from .python_analyzer import TestFunctionAnalysis, analyze_test_module

PLACEHOLDER_PATTERNS = [
    re.compile(r"\bTODO\b", re.I),
    re.compile(r"\bFIXME\b", re.I),
    re.compile(r"\bTBD\b", re.I),
    re.compile(r"待补充"),
    re.compile(r"待实现"),
]


def check_syntax_and_parse(code: str, file_path: str) -> tuple[Optional[ast.AST], Optional[CodeViolation]]:
    """Verify that the code parses cleanly into a valid Python AST."""
    try:
        tree = ast.parse(code, filename=file_path)
        return tree, None
    except SyntaxError as e:
        return None, CodeViolation(
            code=CodeViolationCode.CODE_PARSE_ERROR,
            file_path=file_path,
            line_number=e.lineno,
            message=f"Python syntax error: {e.msg} at line {e.lineno}",
            severity="error",
            suggestion="Fix syntax errors before submitting generated test code.",
        )


def check_placeholders(code: str, file_path: str) -> List[CodeViolation]:
    """Flag placeholder comments or code markers."""
    violations: List[CodeViolation] = []
    lines = code.splitlines()
    for idx, line in enumerate(lines, 1):
        for pat in PLACEHOLDER_PATTERNS:
            if pat.search(line):
                violations.append(
                    CodeViolation(
                        code=CodeViolationCode.PLACEHOLDER_CODE,
                        file_path=file_path,
                        line_number=idx,
                        code_snippet=line.strip(),
                        message=f"Placeholder pattern '{pat.pattern}' found in generated code.",
                        severity="error",
                        suggestion="Provide complete implementation without TODOs or placeholders.",
                    )
                )
                break
    return violations


def validate_test_functions(
    analyses: List[TestFunctionAnalysis],
    file_path: str,
    target_entrypoint: Optional[str] = None,
) -> List[CodeViolation]:
    """Validate discovered test functions against deterministic anti-counterfeit rules."""
    violations: List[CodeViolation] = []

    if not analyses:
        violations.append(
            CodeViolation(
                code=CodeViolationCode.NO_TEST_DISCOVERED,
                file_path=file_path,
                message=f"No test functions (test_*) were discovered in '{file_path}'.",
                severity="error",
                suggestion="Generate at least one test function prefixed with 'test_'.",
            )
        )
        return violations

    for func in analyses:
        # 1. Unconditional skip
        if func.is_unconditionally_skipped:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.UNCONDITIONAL_SKIP,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=func.line_number,
                    message=f"Test function '{func.name}' is unconditionally skipped.",
                    severity="error",
                    suggestion="Remove skip marker and execute test against real target.",
                )
            )

        # 2. Unsupported xfail
        if func.has_unsupported_xfail:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.UNSUPPORTED_XFAIL,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=func.line_number,
                    message=f"Test function '{func.name}' uses unsupported xfail decorator.",
                    severity="error",
                    suggestion="Remove xfail decorator unless tracking an officially documented defect.",
                )
            )

        # 3. Empty test body
        if func.is_empty:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.EMPTY_TEST_BODY,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=func.line_number,
                    message=f"Test function '{func.name}' has an empty body (only pass or docstring).",
                    severity="error",
                    suggestion="Implement concrete test steps and assertions.",
                )
            )
            continue

        # 4. Swallowed exceptions
        for line_no in func.swallowed_exceptions:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.SWALLOWED_EXCEPTION,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=line_no,
                    message=f"Except block in '{func.name}' swallows exceptions without failing or re-raising.",
                    severity="error",
                    suggestion="Use 'pytest.raises(...)', re-raise the exception, or assert expected behavior.",
                )
            )

        # 5. Unreachable assertions
        for line_no in func.unreachable_assertions:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.UNREACHABLE_ASSERTION,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=line_no,
                    message=f"Assertion in '{func.name}' at line {line_no} is unreachable.",
                    severity="error",
                    suggestion="Move assertion before return/exit statement.",
                )
            )

        # 6. SUT interaction check
        has_sut_call = len(func.sut_calls) > 0
        if not has_sut_call and not func.has_pytest_raises:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.NO_SUT_INTERACTION,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=func.line_number,
                    message=f"Test '{func.name}' does not call or interact with the System Under Test (SUT).",
                    severity="error",
                    suggestion=f"Instantiate and call the target system (e.g. {target_entrypoint or 'target component'}).",
                )
            )

        # 7. Fully mocked check
        if func.is_fully_mocked:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.TARGET_FULLY_MOCKED,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=func.line_number,
                    message=f"Test '{func.name}' fully mocks out the target; no real SUT code is exercised.",
                    severity="error",
                    suggestion="Only mock external I/O or network boundaries; do not mock the core component under test.",
                )
            )

        # 8. Assertion analysis
        if not func.assertions and not func.has_pytest_raises:
            violations.append(
                CodeViolation(
                    code=CodeViolationCode.NO_SUT_DEPENDENT_ASSERTION,
                    file_path=file_path,
                    function_name=func.name,
                    line_number=func.line_number,
                    message=f"Test '{func.name}' has no assertions or expected failure checks.",
                    severity="error",
                    suggestion="Add assertions verifying return values or state changes.",
                )
            )
        else:
            has_valid_dependent_assert = False
            for assert_info in func.assertions:
                if assert_info.is_tautology:
                    violations.append(
                        CodeViolation(
                            code=CodeViolationCode.ASSERT_ALWAYS_TRUE,
                            file_path=file_path,
                            function_name=func.name,
                            line_number=assert_info.line_number,
                            code_snippet=assert_info.raw_code,
                            message=f"Assertion '{assert_info.raw_code}' is always True (tautology).",
                            severity="error",
                            suggestion="Assert on actual dynamic results from the target code.",
                        )
                    )
                elif assert_info.is_constant:
                    violations.append(
                        CodeViolation(
                            code=CodeViolationCode.CONSTANT_ASSERTION,
                            file_path=file_path,
                            function_name=func.name,
                            line_number=assert_info.line_number,
                            code_snippet=assert_info.raw_code,
                            message=f"Assertion '{assert_info.raw_code}' compares constant values without testing runtime state.",
                            severity="error",
                            suggestion="Compare SUT output against expected values.",
                        )
                    )
                elif assert_info.is_trivial_not_none:
                    violations.append(
                        CodeViolation(
                            code=CodeViolationCode.TRIVIAL_NOT_NONE_ASSERTION,
                            file_path=file_path,
                            function_name=func.name,
                            line_number=assert_info.line_number,
                            code_snippet=assert_info.raw_code,
                            message=f"Trivial 'is not None' assertion on unrelated variable: '{assert_info.raw_code}'.",
                            severity="error",
                            suggestion="Assert on specific SUT return properties rather than non-nullness of unrelated fixtures.",
                        )
                    )
                elif assert_info.has_sut_dependency:
                    has_valid_dependent_assert = True

            # If none of the assertions depended on SUT and no pytest.raises
            if not has_valid_dependent_assert and not func.has_pytest_raises:
                # Only add if not already flagged as NO_SUT_INTERACTION
                if has_sut_call:
                    violations.append(
                        CodeViolation(
                            code=CodeViolationCode.NO_SUT_DEPENDENT_ASSERTION,
                            file_path=file_path,
                            function_name=func.name,
                            line_number=func.line_number,
                            message=f"Assertions in '{func.name}' do not depend on the output or state of SUT calls.",
                            severity="error",
                            suggestion="Assert on variables returned by or modified by SUT operations.",
                        )
                    )

    return violations
