"""Python AST Analyzer for test functions, fail-closed SUT tracking, and assertion dependencies."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# Standard library modules and utilities that can NEVER be considered System Under Test (SUT)
STDLIB_AND_UTILITY_MODULES: Set[str] = {
    "time", "datetime", "random", "math", "os", "sys", "re", "json", "uuid",
    "pathlib", "shutil", "tempfile", "io", "copy", "collections", "itertools",
    "functools", "logging", "typing", "hashlib", "base64", "urllib", "http",
    "string", "calendar", "glob", "inspect", "operator", "sqlite3", "pickle",
    "csv", "xml", "subprocess", "threading", "multiprocessing", "asyncio",
    "concurrent", "queue", "socket", "ssl", "traceback", "warnings", "weakref",
    "gc", "contextlib", "dis", "platform", "signal", "unittest", "pytest",
}

BUILTIN_AND_FRAMEWORK_FUNCTIONS: Set[str] = {
    "pytest", "unittest", "mock", "MagicMock", "Mock", "patch", "AsyncMock",
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "isinstance", "issubclass", "open", "type", "id",
    "dir", "getattr", "setattr", "hasattr", "repr", "enumerate", "zip",
    "min", "max", "sum", "abs", "round", "all", "any", "sorted", "reversed",
    "sleep", "now", "time", "uuid4", "Path", "dumps", "loads", "search", "match",
}


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
    sut_mutations: List[int] = field(default_factory=list)
    has_real_sut_interaction: bool = False
    assertions: List[AssertionInfo] = field(default_factory=list)
    has_pytest_raises: bool = False
    has_sut_inside_raises: bool = False
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


def _is_disallowed_as_sut(name: str) -> bool:
    """Check if a symbol or call belongs to stdlib, utilities, test framework, or builtins."""
    cleaned = name.strip()
    if cleaned in BUILTIN_AND_FRAMEWORK_FUNCTIONS:
        return True
    root = cleaned.split(".")[0]
    if root in STDLIB_AND_UTILITY_MODULES or root in BUILTIN_AND_FRAMEWORK_FUNCTIONS:
        return True
    return False


class FunctionAstVisitor(ast.NodeVisitor):
    """Detailed AST analyzer for an individual test function with fail-closed SUT tracking."""

    def __init__(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        target_entrypoint: Optional[str] = None,
        local_definitions: Optional[Set[str]] = None,
    ):
        self.func_node = func_node
        self.target_entrypoint = target_entrypoint
        self.target_leaf = _get_target_symbol_leaf(target_entrypoint)
        self.target_full = target_entrypoint.strip() if target_entrypoint else None
        self.local_definitions: Set[str] = set(local_definitions or ())
        self.analysis = TestFunctionAnalysis(
            name=func_node.name,
            line_number=func_node.lineno,
        )
        self._sut_instances: Set[str] = set()
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

        if self.analysis.sut_calls or self.analysis.sut_mutations or self.analysis.has_sut_inside_raises:
            self.analysis.has_real_sut_interaction = True

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
        # 5. Standalone call statement (e.g. cache.clear(), or client.get(...))
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            self._handle_call_expr(stmt.value, lineno=stmt.lineno)
        # 6. Deletion: del cache['a']
        elif isinstance(stmt, ast.Delete):
            self._handle_delete(stmt)

        # Recurse into compound statements
        if isinstance(stmt, (ast.For, ast.While, ast.If)):
            for child in stmt.body:
                self._process_statement(child)
            for child in getattr(stmt, "orelse", []):
                self._process_statement(child)

    def _is_sut_call(self, call: ast.Call) -> tuple[bool, bool, str]:
        """
        Evaluate whether a call is an actual SUT operation.
        Returns: (is_sut, is_mock, func_name)
        """
        func_name = self._get_call_name(call.func)

        # 1. Check if mock
        receiver_is_mock = False
        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
            if call.func.value.id in self._mock_vars:
                receiver_is_mock = True

        is_mock = (
            receiver_is_mock
            or func_name in ("Mock", "MagicMock", "patch", "AsyncMock")
            or "mock" in func_name.lower()
        )
        if is_mock:
            return False, True, func_name

        # 2. Check if local test helper function or fixture defined in test module
        if func_name in self.local_definitions:
            return False, False, func_name

        # 3. Check if disallowed stdlib or builtin (e.g. time.time(), random.random())
        if _is_disallowed_as_sut(func_name):
            # Builtins/stdlib are NEVER SUT by themselves
            return False, False, func_name

        # 4. Check if HTTP API client or UI browser interaction
        if isinstance(call.func, ast.Attribute):
            attr_name = call.func.attr
            base_name = self._get_call_name(call.func.value)
            if attr_name in ("get", "post", "put", "delete", "patch", "options", "head", "request"):
                if (
                    base_name in ("requests", "httpx", "aiohttp", "client", "test_client", "api_client", "session", "http_client", "app")
                    or base_name.endswith("client")
                    or base_name.endswith("session")
                ):
                    return True, False, func_name
            elif attr_name in ("goto", "click", "fill", "locator", "get_by_role", "get_by_text", "wait_for_selector", "find_element"):
                if (
                    base_name in ("page", "browser", "driver", "context")
                    or base_name.endswith("page")
                    or base_name.endswith("driver")
                ):
                    return True, False, func_name

        # 5. If target_entrypoint is provided: FAIL-CLOSED
        if self.target_leaf:
            # Case 5a: Direct call/instantiation of target symbol (e.g. LRUCache(10))
            if (
                func_name == self.target_leaf
                or func_name == self.target_full
                or func_name.endswith(f".{self.target_leaf}")
            ):
                return True, False, func_name

            # Case 4b: Method call on an SUT instance (e.g. cache.get(...), cache.popitem())
            if isinstance(call.func, ast.Attribute):
                recv = call.func.value
                if isinstance(recv, ast.Name) and recv.id in self._sut_instances:
                    return True, False, func_name
                elif isinstance(recv, ast.Attribute) and getattr(recv, "attr", "") in self._sut_instances:
                    return True, False, func_name

            # Case 4c: SUT instance passed as primary argument to an inspected function
            if any(name in self._sut_instances for name in self._extract_names(call)):
                return True, False, func_name

            # FAIL-CLOSED: Any other function call (e.g. time.time(), unrelated helper) is NOT SUT!
            return False, False, func_name

        # 5. If target_entrypoint is NOT provided (fallback mode):
        # We cannot identify SUT. Unrelated helpers/functions are NOT SUT!
        if isinstance(call.func, ast.Attribute):
            recv = call.func.value
            if isinstance(recv, ast.Name) and recv.id in self._sut_instances:
                return True, False, func_name

        # Without target identity, arbitrary functions or helpers are NOT SUT!
        return False, False, func_name

    def _handle_assignment(self, stmt: ast.Assign | ast.AnnAssign) -> None:
        targets: List[str] = []
        is_subscript_mutation = False

        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    targets.append(t.id)
                elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                    # e.g. cache['a'] = 1 -> SUT mutation
                    if t.value.id in self._sut_instances:
                        is_subscript_mutation = True
                        self.analysis.sut_mutations.append(stmt.lineno)
                        self.analysis.has_real_sut_interaction = True
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
            is_sut, is_mock, func_name = self._is_sut_call(val)
            target_repr = targets[0] if targets else None

            if is_mock:
                for t in targets:
                    self._mock_vars.add(t)
                self.analysis.sut_calls.append(
                    SUTCallInfo(target_name=func_name, assigned_to=target_repr, line_number=stmt.lineno, is_mock=True)
                )

            elif is_sut:
                for t in targets:
                    # If this is constructing or creating the SUT:
                    if self.target_leaf and (func_name == self.target_leaf or func_name.endswith(f".{self.target_leaf}")):
                        self._sut_instances.add(t)
                    elif not self.target_leaf:
                        # Fallback mode: first non-stdlib constructor/call creates an SUT instance
                        self._sut_instances.add(t)

                    self._sut_vars.add(t)

                self.analysis.sut_calls.append(
                    SUTCallInfo(target_name=func_name, assigned_to=target_repr, line_number=stmt.lineno, is_mock=False)
                )
                self.analysis.has_real_sut_interaction = True

        elif isinstance(val, ast.Subscript) and isinstance(val.value, ast.Name):
            # e.g. item = cache['a']
            if val.value.id in self._sut_instances:
                self.analysis.has_real_sut_interaction = True
                for t in targets:
                    self._sut_vars.add(t)

        else:
            referenced = self._extract_names(val)
            if any(name in self._mock_vars for name in referenced):
                for t in targets:
                    self._mock_vars.add(t)
            elif any(name in self._sut_vars for name in referenced):
                for t in targets:
                    self._sut_vars.add(t)

    def _handle_call_expr(self, call: ast.Call, lineno: int) -> None:
        is_sut, is_mock, func_name = self._is_sut_call(call)
        if is_sut:
            self.analysis.sut_calls.append(
                SUTCallInfo(target_name=func_name, assigned_to=None, line_number=lineno, is_mock=False)
            )
            self.analysis.has_real_sut_interaction = True
        elif is_mock:
            self.analysis.sut_calls.append(
                SUTCallInfo(target_name=func_name, assigned_to=None, line_number=lineno, is_mock=True)
            )

    def _handle_delete(self, stmt: ast.Delete) -> None:
        for t in stmt.targets:
            if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                if t.value.id in self._sut_instances:
                    self.analysis.sut_mutations.append(stmt.lineno)
                    self.analysis.has_real_sut_interaction = True

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
        is_raises_block = False
        for item in stmt.items:
            if isinstance(item.context_expr, ast.Call):
                name = self._get_call_name(item.context_expr.func)
                if "raises" in name or "warns" in name:
                    is_raises_block = True
                    self.analysis.has_pytest_raises = True

        # Process statements inside with block
        for body_stmt in stmt.body:
            if is_raises_block:
                if self._statement_interacts_with_sut(body_stmt):
                    self.analysis.has_sut_inside_raises = True
                    self.analysis.has_real_sut_interaction = True

            self._process_statement(body_stmt)

    def _statement_interacts_with_sut(self, stmt: ast.stmt) -> bool:
        """Check if a statement directly triggers an SUT operation inside a raises block."""
        if isinstance(stmt, ast.Expr):
            if isinstance(stmt.value, ast.Call):
                is_sut, _, _ = self._is_sut_call(stmt.value)
                return is_sut
            elif isinstance(stmt.value, ast.Subscript) and isinstance(stmt.value.value, ast.Name):
                # e.g. cache["missing"]
                return stmt.value.value.id in self._sut_instances
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            if isinstance(stmt.value, ast.Call):
                is_sut, _, _ = self._is_sut_call(stmt.value)
                return is_sut
            elif isinstance(stmt.value, ast.Subscript) and isinstance(stmt.value.value, ast.Name):
                return stmt.value.value.id in self._sut_instances
        elif isinstance(stmt, ast.Delete):
            for t in stmt.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                    return t.value.id in self._sut_instances

        # A bare raise statement (e.g. raise ValueError("fake")) is NEVER SUT interaction
        return False

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

    local_definitions: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_definitions.add(node.name)

    results: List[TestFunctionAnalysis] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") or node.name.startswith("test"):
                visitor = FunctionAstVisitor(
                    node,
                    target_entrypoint=target_entrypoint,
                    local_definitions=local_definitions,
                )
                analysis = visitor.analyze()
                results.append(analysis)
    return results
