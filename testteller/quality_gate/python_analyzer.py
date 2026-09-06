"""Python AST Analyzer for test functions and assertion dependency tracking."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class SUTCallInfo:
    target_name: str
    assigned_to: Optional[str]
    line_number: int
    is_mock: bool = False


@dataclass
class AssertionInfo:
    line_number: int
    raw_code: str
    is_tautology: bool
    is_constant: bool
    referenced_names: Set[str]
    has_sut_dependency: bool = False
    is_trivial_not_none: bool = False


@dataclass
class TestFunctionAnalysis:
    name: str
    line_number: int
    is_empty: bool = False
    docstring: Optional[str] = None
    sut_calls: List[SUTCallInfo] = field(default_factory=list)
    sut_derived_vars: Set[str] = field(default_factory=set)
    assertions: List[AssertionInfo] = field(default_factory=list)
    has_pytest_raises: bool = False
    swallowed_exceptions: List[int] = field(default_factory=list)
    unreachable_assertions: List[int] = field(default_factory=list)
    is_unconditionally_skipped: bool = False
    has_unsupported_xfail: bool = False
    is_fully_mocked: bool = False


def _get_target_symbol_leaf(target_entrypoint: Optional[str]) -> Optional[str]:
    """Extract leaf symbol name from target entrypoint (e.g. 'cachetools.LRUCache' -> 'LRUCache')."""
    if not target_entrypoint:
        return None
    cleaned = target_entrypoint.strip()
    if ":" in cleaned:
        cleaned = cleaned.split(":")[-1]
    return cleaned.split(".")[-1]


def _is_framework_or_builtin_name(name: str) -> bool:
    """Check if a symbol name is a common test framework, mock, or builtin."""
    builtins_and_frameworks = {
        "pytest", "unittest", "mock", "MagicMock", "Mock", "patch", "AsyncMock",
        "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
        "set", "tuple", "isinstance", "issubclass", "open", "type", "id",
        "dir", "getattr", "setattr", "hasattr", "repr", "enumerate", "zip",
    }
    return name in builtins_and_frameworks


class FunctionAstVisitor(ast.NodeVisitor):
    """Detailed AST analyzer for an individual test function."""

    def __init__(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, target_entrypoint: Optional[str] = None):
        self.func_node = func_node
        self.target_leaf = _get_target_symbol_leaf(target_entrypoint)
        self.analysis = TestFunctionAnalysis(
            name=func_node.name,
            line_number=func_node.lineno,
        )
        self._sut_vars: Set[str] = set()
        self._mock_vars: Set[str] = set()

    def analyze(self) -> TestFunctionAnalysis:
        # Check decorators for skip / xfail
        for dec in self.func_node.decorator_list:
            dec_id = ""
            if isinstance(dec, ast.Name):
                dec_id = dec.id
            elif isinstance(dec, ast.Attribute):
                dec_id = f"{getattr(dec.value, 'id', '')}.{dec.attr}"
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    dec_id = dec.func.id
                elif isinstance(dec.func, ast.Attribute):
                    dec_id = f"{getattr(dec.func.value, 'id', '')}.{dec.func.attr}"

            if "skip" in dec_id.lower():
                self.analysis.is_unconditionally_skipped = True
            if "xfail" in dec_id.lower():
                self.analysis.has_unsupported_xfail = True

        # Check empty body (e.g. only pass or docstring)
        non_doc_stmts = [
            s for s in self.func_node.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
        ]
        if not non_doc_stmts or all(isinstance(s, ast.Pass) for s in non_doc_stmts):
            self.analysis.is_empty = True
            return self.analysis

        # Check statement flow
        has_returned = False
        for stmt in self.func_node.body:
            if has_returned:
                if isinstance(stmt, ast.Assert):
                    self.analysis.unreachable_assertions.append(stmt.lineno)
            if isinstance(stmt, (ast.Return, ast.Raise)):
                has_returned = True
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Attribute) and call.func.attr in ("skip", "exit"):
                    has_returned = True

            self._process_statement(stmt)

        # Check if fully mocked
        if self.analysis.sut_calls and all(c.is_mock for c in self.analysis.sut_calls):
            self.analysis.is_fully_mocked = True

        self.analysis.sut_derived_vars = set(self._sut_vars)
        return self.analysis

    def _process_statement(self, stmt: ast.stmt) -> None:
        # 1. Assignment: target = value
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            self._handle_assignment(stmt)
        # 2. Assert statement
        elif isinstance(stmt, ast.Assert):
            self._handle_assert(stmt)
        # 3. With block (check for pytest.raises)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            self._handle_with(stmt)
        # 4. Try block (check for swallowed exceptions)
        elif isinstance(stmt, ast.Try):
            self._handle_try(stmt)
        # 5. Standalone call statement (e.g. cache['a'] = 1, or client.get(...))
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            self._handle_call_expr(stmt.value)
        # 6. Augmented assign or subscript assign: cache['a'] = 1
        elif isinstance(stmt, ast.Assign):
            pass

        # Recurse into compound statements
        if isinstance(stmt, (ast.For, ast.While, ast.If)):
            for child in stmt.body:
                self._process_statement(child)
            for child in getattr(stmt, "orelse", []):
                self._process_statement(child)

    def _handle_assignment(self, stmt: ast.Assign | ast.AnnAssign) -> None:
        targets: List[str] = []
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    targets.append(t.id)
                elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                    # e.g. cache['a'] = 1 -> mutation on SUT object
                    if t.value.id in self._sut_vars:
                        self._sut_vars.add(t.value.id)
            val = stmt.value
        else:
            if isinstance(stmt.target, ast.Name):
                targets.append(stmt.target.id)
            val = stmt.value

        if not val:
            return

        # Check what is being assigned
        if isinstance(val, ast.Call):
            func_name = self._get_call_name(val.func)
            receiver_is_mock = False
            if isinstance(val.func, ast.Attribute) and isinstance(val.func.value, ast.Name):
                if val.func.value.id in self._mock_vars:
                    receiver_is_mock = True

            is_mock = receiver_is_mock or func_name in ("Mock", "MagicMock", "patch") or "mock" in func_name.lower()

            # Is it an SUT call?
            is_sut = False
            if not is_mock:
                if self.target_leaf and (func_name == self.target_leaf or self.target_leaf in func_name):
                    is_sut = True
                elif not _is_framework_or_builtin_name(func_name):
                    is_sut = True
                elif any(arg_name in self._sut_vars for arg_name in self._extract_names(val)):
                    is_sut = True

            target_repr = targets[0] if targets else None
            self.analysis.sut_calls.append(
                SUTCallInfo(target_name=func_name, assigned_to=target_repr, line_number=stmt.lineno, is_mock=is_mock)
            )

            if is_mock:
                for t in targets:
                    self._mock_vars.add(t)
            elif is_sut:
                for t in targets:
                    self._sut_vars.add(t)

        # Derivation from another variable: e.g. status = response.status_code or data = cache['a']
        else:
            referenced = self._extract_names(val)
            if any(name in self._mock_vars for name in referenced):
                for t in targets:
                    self._mock_vars.add(t)
            elif any(name in self._sut_vars for name in referenced):
                for t in targets:
                    self._sut_vars.add(t)

    def _handle_call_expr(self, call: ast.Call) -> None:
        func_name = self._get_call_name(call.func)
        receiver_is_mock = False
        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
            if call.func.value.id in self._mock_vars:
                receiver_is_mock = True

        is_mock = receiver_is_mock or func_name in ("Mock", "MagicMock", "patch") or "mock" in func_name.lower()
        is_sut = False

        if not is_mock:
            if self.target_leaf and (func_name == self.target_leaf or self.target_leaf in func_name):
                is_sut = True
            elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
                base_var = call.func.value.id
                if base_var in self._sut_vars:
                    is_sut = True
            elif not _is_framework_or_builtin_name(func_name):
                is_sut = True

        self.analysis.sut_calls.append(
            SUTCallInfo(target_name=func_name, assigned_to=None, line_number=call.lineno, is_mock=is_mock)
        )

    def _handle_assert(self, stmt: ast.Assert) -> None:
        raw_code = ast.unparse(stmt) if hasattr(ast, "unparse") else "assert"
        referenced = self._extract_names(stmt.test)

        is_tautology = self._check_tautology(stmt.test)
        is_constant = self._check_constant(stmt.test)

        # Check trivial "x is not None" where x is not from SUT
        is_trivial_not_none = False
        if isinstance(stmt.test, ast.Compare) and len(stmt.test.ops) == 1:
            op = stmt.test.ops[0]
            comparator = stmt.test.comparators[0]
            if isinstance(op, ast.IsNot) and isinstance(comparator, ast.Constant) and comparator.value is None:
                if not any(name in self._sut_vars for name in referenced):
                    is_trivial_not_none = True

        # Does this assertion depend on SUT?
        has_sut_dep = any(name in self._sut_vars for name in referenced)

        self.analysis.assertions.append(
            AssertionInfo(
                line_number=stmt.lineno,
                raw_code=raw_code,
                is_tautology=is_tautology,
                is_constant=is_constant,
                referenced_names=referenced,
                has_sut_dependency=has_sut_dep,
                is_trivial_not_none=is_trivial_not_none,
            )
        )

    def _handle_with(self, stmt: ast.With | ast.AsyncWith) -> None:
        for item in stmt.items:
            if isinstance(item.context_expr, ast.Call):
                name = self._get_call_name(item.context_expr.func)
                if "raises" in name or "warns" in name:
                    self.analysis.has_pytest_raises = True
                    # If target is inside the with body, consider it SUT interaction
                    for body_stmt in stmt.body:
                        self._process_statement(body_stmt)

    def _handle_try(self, stmt: ast.Try) -> None:
        for handler in stmt.handlers:
            if handler.type is None:  # bare except:
                if self._is_swallowed_body(handler.body):
                    self.analysis.swallowed_exceptions.append(handler.lineno)
            elif isinstance(handler.type, ast.Name) and handler.type.id in ("Exception", "BaseException"):
                if self._is_swallowed_body(handler.body):
                    self.analysis.swallowed_exceptions.append(handler.lineno)
        # Also process try body
        for body_stmt in stmt.body:
            self._process_statement(body_stmt)

    def _is_swallowed_body(self, body: List[ast.stmt]) -> bool:
        for s in body:
            if isinstance(s, (ast.Raise, ast.Assert)):
                return False
            if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                name = self._get_call_name(s.value.func)
                if "fail" in name:
                    return False
        return True

    def _get_call_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            base = self._get_call_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""

    def _extract_names(self, node: ast.AST) -> Set[str]:
        names: Set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                names.add(child.id)
        return names

    def _check_tautology(self, test_node: ast.AST) -> bool:
        if isinstance(test_node, ast.Constant) and bool(test_node.value) is True:
            return True
        if isinstance(test_node, ast.UnaryOp) and isinstance(test_node.op, ast.Not):
            if isinstance(test_node.operand, ast.Constant) and bool(test_node.operand.value) is False:
                return True
        if isinstance(test_node, ast.Compare):
            left = test_node.left
            for op, right in zip(test_node.ops, test_node.comparators):
                if isinstance(op, (ast.Eq, ast.Is)):
                    if isinstance(left, ast.Name) and isinstance(right, ast.Name) and left.id == right.id:
                        return True
                    if isinstance(left, ast.Constant) and isinstance(right, ast.Constant) and left.value == right.value:
                        return True
                left = right
        return False

    def _check_constant(self, test_node: ast.AST) -> bool:
        if isinstance(test_node, ast.Constant):
            return True
        if isinstance(test_node, ast.Compare):
            left = test_node.left
            for op, right in zip(test_node.ops, test_node.comparators):
                if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
                    return True
                left = right
        return False


def analyze_test_module(code: str, target_entrypoint: Optional[str] = None) -> List[TestFunctionAnalysis]:
    """Parse test code and return analysis for every discovered test function."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    results: List[TestFunctionAnalysis] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") or node.name.startswith("test"):
                visitor = FunctionAstVisitor(node, target_entrypoint=target_entrypoint)
                analysis = visitor.analyze()
                results.append(analysis)
    return results
