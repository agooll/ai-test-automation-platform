"""Grounding catalog, symbol extractors, and evidence-backed anti-hallucination validation."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

from .code_models import (
    ClaimItem,
    CodeViolation,
    CodeViolationCode,
    EvidenceItem,
    GroundingFinding,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Repo & AST Symbol Extractor
# ---------------------------------------------------------------------------

class RepoSymbolExtractor:
    """Extracts authoritative, exported symbols from Python files and repositories."""

    EXCLUDED_DIRS: Set[str] = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        "tests",
        "test",
        "build",
        "dist",
        ".tox",
        "docs",
    }

    @classmethod
    def extract_from_file(
        cls,
        file_path: Path | str,
        module_prefix: str = "",
    ) -> List[EvidenceItem]:
        """Extract classes, functions, and __all__ symbols from a single Python file."""
        file_path = Path(file_path)
        if not file_path.exists() or not file_path.is_file():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))
        except Exception as e:
            logger.warning("Failed to parse Python file %s: %e", file_path, e)
            return []

        items: List[EvidenceItem] = []
        source_str = str(file_path)

        # 1. Check for __all__
        explicit_all: Optional[Set[str]] = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            names = set()
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    names.add(elt.value)
                            explicit_all = names

        # 2. Extract top-level classes and functions
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                qname = f"{module_prefix}.{class_name}" if module_prefix else class_name
                items.append(
                    EvidenceItem(
                        evidence_id=f"SYM-CLASS-{qname}",
                        kind="target_symbol",
                        value=qname,
                        source=source_str,
                        confidence=1.0,
                    )
                )
                if module_prefix:
                    # Also register short name
                    items.append(
                        EvidenceItem(
                            evidence_id=f"SYM-CLASS-SHORT-{class_name}",
                            kind="target_symbol",
                            value=class_name,
                            source=source_str,
                            confidence=1.0,
                        )
                    )

                # Extract public methods on class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = item.name
                        method_qname = f"{qname}.{method_name}"
                        items.append(
                            EvidenceItem(
                                evidence_id=f"SYM-METHOD-{method_qname}",
                                kind="target_symbol",
                                value=method_qname,
                                source=source_str,
                                confidence=1.0,
                            )
                        )

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_name = node.name
                qname = f"{module_prefix}.{fn_name}" if module_prefix else fn_name
                items.append(
                    EvidenceItem(
                        evidence_id=f"SYM-FN-{qname}",
                        kind="target_symbol",
                        value=qname,
                        source=source_str,
                        confidence=1.0,
                    )
                )
                if module_prefix:
                    items.append(
                        EvidenceItem(
                            evidence_id=f"SYM-FN-SHORT-{fn_name}",
                            kind="target_symbol",
                            value=fn_name,
                            source=source_str,
                            confidence=1.0,
                        )
                    )

        # 3. If __all__ was explicitly specified, ensure all symbols in __all__ are present
        if explicit_all:
            for exported_name in explicit_all:
                qname = f"{module_prefix}.{exported_name}" if module_prefix else exported_name
                items.append(
                    EvidenceItem(
                        evidence_id=f"SYM-ALL-{qname}",
                        kind="target_symbol",
                        value=qname,
                        source=source_str,
                        confidence=1.0,
                    )
                )
                if module_prefix:
                    items.append(
                        EvidenceItem(
                            evidence_id=f"SYM-ALL-SHORT-{exported_name}",
                            kind="target_symbol",
                            value=exported_name,
                            source=source_str,
                            confidence=1.0,
                        )
                    )

        return items

    @classmethod
    def extract_from_directory(
        cls,
        root_dir: Path | str,
        package_name: Optional[str] = None,
        excludes: Optional[Set[str]] = None,
    ) -> List[EvidenceItem]:
        """Recursively scan a directory for Python modules and extract authoritative symbols."""
        root = Path(root_dir)
        if not root.exists():
            return []

        excluded = cls.EXCLUDED_DIRS | (excludes or set())
        items: List[EvidenceItem] = []

        for py_file in root.rglob("*.py"):
            # Skip if any parent is excluded
            if any(part in excluded for part in py_file.parts):
                continue

            rel_parts = py_file.relative_to(root).parts
            # Determine module prefix
            module_parts = list(rel_parts)
            if module_parts[-1] == "__init__.py":
                module_parts.pop()
            else:
                module_parts[-1] = module_parts[-1][:-3]

            prefix_components = []
            if package_name:
                prefix_components.append(package_name)
            prefix_components.extend(module_parts)
            mod_prefix = ".".join(filter(None, prefix_components))

            file_items = cls.extract_from_file(py_file, module_prefix=mod_prefix)
            items.extend(file_items)

            # Also register the module itself as a target_symbol
            if mod_prefix:
                items.append(
                    EvidenceItem(
                        evidence_id=f"SYM-MOD-{mod_prefix}",
                        kind="target_symbol",
                        value=mod_prefix,
                        source=str(py_file),
                        confidence=1.0,
                    )
                )

        return items

    @classmethod
    def extract_from_entrypoint(
        cls,
        target_entrypoint: str,
        repo_root: Optional[Path | str] = None,
    ) -> List[EvidenceItem]:
        """Extract authoritative symbols around a target entrypoint (e.g. 'cachetools.LRUCache')."""
        items: List[EvidenceItem] = []
        parts = target_entrypoint.split(".")
        pkg_or_mod = parts[0]

        # Always add the full entrypoint as strong evidence
        items.append(
            EvidenceItem(
                evidence_id=f"SYM-EP-{target_entrypoint}",
                kind="target_symbol",
                value=target_entrypoint,
                source="target_entrypoint",
                confidence=1.0,
            )
        )
        if len(parts) > 1:
            # Short symbol name (e.g. LRUCache)
            items.append(
                EvidenceItem(
                    evidence_id=f"SYM-EP-SHORT-{parts[-1]}",
                    kind="target_symbol",
                    value=parts[-1],
                    source="target_entrypoint",
                    confidence=1.0,
                )
            )

        # If repo_root is provided, look for the package directory or module file
        if repo_root:
            root = Path(repo_root)
            candidates = [
                root / pkg_or_mod,
                root / "src" / pkg_or_mod,
                root / f"{pkg_or_mod}.py",
                root / "src" / f"{pkg_or_mod}.py",
            ]
            for cand in candidates:
                if cand.is_dir():
                    scanned = cls.extract_from_directory(cand, package_name=pkg_or_mod)
                    items.extend(scanned)
                    break
                elif cand.is_file():
                    scanned = cls.extract_from_file(cand, module_prefix=pkg_or_mod)
                    items.extend(scanned)
                    break

        return items


# ---------------------------------------------------------------------------
# 2. Code Claim Extractor (AST Analysis of Generated Tests)
# ---------------------------------------------------------------------------

class CodeClaimExtractor(ast.NodeVisitor):
    """AST visitor extracting verifiable API, UI, model field, and target symbol claims."""

    HTTP_METHODS: Set[str] = {"get", "post", "put", "delete", "patch", "options", "head"}
    UI_LOCATOR_METHODS: Set[str] = {
        "locator",
        "click",
        "fill",
        "hover",
        "text_content",
        "wait_for_selector",
        "find_element",
        "find_elements",
        "get_by_role",
        "get_by_test_id",
        "get_by_text",
        "get_by_placeholder",
        "get_by_label",
    }

    def __init__(
        self,
        file_path: str,
        target_entrypoint: Optional[str] = None,
    ):
        self.file_path = file_path
        self.target_entrypoint = target_entrypoint
        self.target_pkg: Optional[str] = target_entrypoint.split(".")[0] if target_entrypoint else None
        self.claims: List[ClaimItem] = []
        self._claim_counter = 0
        self.sut_var_types: Dict[str, str] = {}

    def _next_id(self, kind: str) -> str:
        self._claim_counter += 1
        return f"C-{kind.upper()}-{self._claim_counter:03d}"

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            func_name = ""
            if isinstance(node.value.func, ast.Name):
                func_name = node.value.func.id
            elif isinstance(node.value.func, ast.Attribute):
                func_name = node.value.func.attr
            if func_name and (func_name == self.target_entrypoint or (self.target_entrypoint and func_name in self.target_entrypoint)):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.sut_var_types[t.id] = func_name
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Track module imports matching target package."""
        if self.target_pkg:
            for alias in node.names:
                if alias.name == self.target_pkg or alias.name.startswith(f"{self.target_pkg}."):
                    self.claims.append(
                        ClaimItem(
                            claim_id=self._next_id("target_symbol"),
                            kind="target_symbol",
                            value=alias.name,
                            file_path=self.file_path,
                            line_number=node.lineno,
                            status="UNKNOWN",
                        )
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Track imported symbols from target package."""
        if self.target_pkg and node.module:
            if node.module == self.target_pkg or node.module.startswith(f"{self.target_pkg}."):
                for alias in node.names:
                    full_symbol = f"{node.module}.{alias.name}"
                    self.claims.append(
                        ClaimItem(
                            claim_id=self._next_id("target_symbol"),
                            kind="target_symbol",
                            value=full_symbol,
                            file_path=self.file_path,
                            line_number=node.lineno,
                            status="UNKNOWN",
                        )
                    )
                    # Also record the symbol name itself (e.g. LRUCache)
                    self.claims.append(
                        ClaimItem(
                            claim_id=self._next_id("target_symbol"),
                            kind="target_symbol",
                            value=alias.name,
                            file_path=self.file_path,
                            line_number=node.lineno,
                            status="UNKNOWN",
                        )
                    )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect function/method calls for API endpoints and UI selectors."""
        # 1. Check for API calls (requests.get, httpx.post, client.get, etc.)
        self._check_api_call(node)

        # 2. Check for UI locator calls (page.locator, page.click, etc.)
        self._check_ui_call(node)

        # 3. Check for method calls on SUT instances
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            recv_var = node.func.value.id
            method_name = node.func.attr
            if recv_var in self.sut_var_types:
                cls_name = self.sut_var_types[recv_var]
                if not method_name.startswith("__"):
                    self.claims.append(
                        ClaimItem(
                            claim_id=self._next_id("target_symbol"),
                            kind="target_symbol",
                            value=f"{cls_name}.{method_name}",
                            file_path=self.file_path,
                            line_number=node.lineno,
                            status="UNKNOWN",
                        )
                    )

        self.generic_visit(node)

    def _check_api_call(self, node: ast.Call) -> None:
        """Check if call is an HTTP request and extract method, path, and payload keys."""
        method_name: Optional[str] = None
        is_http_call = False

        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr.lower()
            if attr in self.HTTP_METHODS:
                # Receiver can be requests, httpx, client, test_client, self.client
                recv = node.func.value
                if isinstance(recv, ast.Name):
                    recv_name = recv.id.lower()
                    if recv_name in {"requests", "httpx", "client", "test_client", "session", "api"}:
                        is_http_call = True
                        method_name = attr.upper()
                    elif "client" in recv_name:
                        is_http_call = True
                        method_name = attr.upper()
                elif isinstance(recv, ast.Attribute):
                    # e.g. self.client.get(...)
                    if "client" in recv.attr.lower():
                        is_http_call = True
                        method_name = attr.upper()
            elif attr == "request":
                # requests.request('POST', url, ...)
                if isinstance(node.func.value, ast.Name) and node.func.value.id.lower() in {
                    "requests",
                    "httpx",
                    "session",
                    "client",
                }:
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        is_http_call = True
                        method_name = node.args[0].value.upper()

        if is_http_call and method_name:
            # Extract URL/path argument
            url_str = self._extract_url_arg(node)
            if url_str:
                normalized_path = self._normalize_endpoint_path(url_str)
                claim_val = f"{method_name} {normalized_path}"
                self.claims.append(
                    ClaimItem(
                        claim_id=self._next_id("api_endpoint"),
                        kind="api_endpoint",
                        value=claim_val,
                        file_path=self.file_path,
                        line_number=node.lineno,
                        status="UNKNOWN",
                    )
                )

            # Extract payload field keys if json={...} keyword is passed
            for kw in node.keywords:
                if kw.arg == "json" and isinstance(kw.value, ast.Dict):
                    for k in kw.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            self.claims.append(
                                ClaimItem(
                                    claim_id=self._next_id("model_field"),
                                    kind="model_field",
                                    value=k.value,
                                    file_path=self.file_path,
                                    line_number=node.lineno,
                                    status="UNKNOWN",
                                )
                            )

    def _check_ui_call(self, node: ast.Call) -> None:
        """Check if call is a UI interaction/locator and extract selector."""
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in self.UI_LOCATOR_METHODS:
                # Extract first string argument or keyword argument
                selector_val: Optional[str] = None
                if node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        selector_val = first_arg.value
                    elif len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                        # Selenium driver.find_element(By.ID, "some_id")
                        selector_val = node.args[1].value

                if not selector_val:
                    for kw in node.keywords:
                        if kw.arg in {"selector", "name", "text"} and isinstance(kw.value, ast.Constant) and isinstance(kw.value, str):
                            selector_val = kw.value
                            break

                if selector_val:
                    self.claims.append(
                        ClaimItem(
                            claim_id=self._next_id("ui_selector"),
                            kind="ui_selector",
                            value=selector_val,
                            file_path=self.file_path,
                            line_number=node.lineno,
                            status="UNKNOWN",
                        )
                    )

    def _extract_url_arg(self, node: ast.Call) -> Optional[str]:
        """Extract the URL string literal from an HTTP call."""
        # Check keyword arg 'url'
        for kw in node.keywords:
            if kw.arg == "url" and isinstance(kw.value, ast.Constant) and isinstance(kw.value, str):
                return kw.value

        # Check positional args: for .request('POST', url) it's index 1, otherwise index 0
        is_request_method = isinstance(node.func, ast.Attribute) and node.func.attr.lower() == "request"
        arg_idx = 1 if is_request_method else 0

        if len(node.args) > arg_idx:
            arg = node.args[arg_idx]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
            elif isinstance(arg, ast.JoinedStr):
                # f-string: reconstruct literal parts (e.g. f"/api/users/{user_id}" -> "/api/users/{}")
                parts = []
                for val in arg.values:
                    if isinstance(val, ast.Constant) and isinstance(val.value, str):
                        parts.append(val.value)
                    else:
                        parts.append("{}")
                return "".join(parts)

        return None

    @staticmethod
    def _normalize_endpoint_path(url_or_path: str) -> str:
        """Extract path component from URL and normalize trailing slashes."""
        if "://" in url_or_path:
            parsed = urlparse(url_or_path)
            path = parsed.path
        else:
            path = url_or_path.split("?")[0]

        path = path.strip()
        if not path.startswith("/"):
            path = f"/{path}"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path


# ---------------------------------------------------------------------------
# 3. Evidence Catalog
# ---------------------------------------------------------------------------

class EvidenceCatalog:
    """Aggregates and queries verified project evidence for anti-hallucination validation."""

    def __init__(self, items: Optional[Iterable[EvidenceItem]] = None):
        self._items_by_kind: Dict[str, List[EvidenceItem]] = {
            "api_endpoint": [],
            "ui_selector": [],
            "model_field": [],
            "target_symbol": [],
            "config": [],
            "auth_pattern": [],
        }
        self._exact_index: Dict[Tuple[str, str], EvidenceItem] = {}

        if items:
            self.add_items(items)

    def add_item(self, item: EvidenceItem) -> None:
        """Add an evidence item into catalog."""
        if item.kind not in self._items_by_kind:
            self._items_by_kind[item.kind] = []
        self._items_by_kind[item.kind].append(item)
        norm_key = (item.kind, self._normalize_value(item.kind, item.value))
        self._exact_index[norm_key] = item

    def add_items(self, items: Iterable[EvidenceItem]) -> None:
        for item in items:
            self.add_item(item)

    def has_domain(self, kind: str) -> bool:
        """Return True if this catalog contains verified domain knowledge for this kind."""
        return bool(self._items_by_kind.get(kind))

    def get_items(self, kind: Optional[str] = None) -> List[EvidenceItem]:
        if kind:
            return list(self._items_by_kind.get(kind, []))
        all_items: List[EvidenceItem] = []
        for lst in self._items_by_kind.values():
            all_items.extend(lst)
        return all_items

    def find_match(self, claim: ClaimItem) -> Optional[EvidenceItem]:
        """Attempt to match a claim against catalog evidence."""
        norm_claim_val = self._normalize_value(claim.kind, claim.value)
        key = (claim.kind, norm_claim_val)
        if key in self._exact_index:
            return self._exact_index[key]

        # Domain-specific fuzzy/prefix matching
        if claim.kind == "api_endpoint":
            return self._match_api_endpoint(claim.value)
        elif claim.kind == "target_symbol":
            return self._match_target_symbol(claim.value)
        elif claim.kind == "model_field":
            return self._match_model_field(claim.value)

        return None

    def _normalize_value(self, kind: str, value: str) -> str:
        val = value.strip()
        if kind == "api_endpoint":
            parts = val.split(maxsplit=1)
            if len(parts) == 2:
                method, path = parts[0].upper(), parts[1]
                path = CodeClaimExtractor._normalize_endpoint_path(path)
                return f"{method} {path}"
            return val.upper()
        elif kind == "ui_selector":
            return val.strip("\"'")
        return val

    def _match_api_endpoint(self, claim_val: str) -> Optional[EvidenceItem]:
        parts = claim_val.strip().split(maxsplit=1)
        if len(parts) != 2:
            return None
        c_method, c_path = parts[0].upper(), CodeClaimExtractor._normalize_endpoint_path(parts[1])

        for ev in self._items_by_kind.get("api_endpoint", []):
            ev_parts = ev.value.strip().split(maxsplit=1)
            if len(ev_parts) == 2:
                e_method, e_path = ev_parts[0].upper(), CodeClaimExtractor._normalize_endpoint_path(ev_parts[1])
                if c_method == e_method:
                    if c_path == e_path or self._path_matches_template(template=e_path, concrete=c_path):
                        return ev
            elif len(ev_parts) == 1:
                e_path = CodeClaimExtractor._normalize_endpoint_path(ev_parts[0])
                if c_path == e_path or self._path_matches_template(template=e_path, concrete=c_path):
                    return ev
        return None

    def _match_target_symbol(self, claim_val: str) -> Optional[EvidenceItem]:
        c_val = claim_val.strip()
        short_c_val = c_val.split(".")[-1]

        for ev in self._items_by_kind.get("target_symbol", []):
            if ev.value == c_val:
                return ev
            # Qualified name ending with symbol name: e.g. cachetools.LRUCache matches LRUCache
            ev_short = ev.value.split(".")[-1]
            if short_c_val == ev_short:
                return ev
        return None

    def _match_model_field(self, claim_val: str) -> Optional[EvidenceItem]:
        c_val = claim_val.strip()
        short_field = c_val.split(".")[-1]

        for ev in self._items_by_kind.get("model_field", []):
            if ev.value == c_val or ev.value.endswith(f".{short_field}"):
                return ev
        return None

    @staticmethod
    def _path_matches_template(template: str, concrete: str) -> bool:
        t_parts = template.strip("/").split("/")
        c_parts = concrete.strip("/").split("/")
        if len(t_parts) != len(c_parts):
            return False
        for t, c in zip(t_parts, c_parts):
            if t.startswith("{") and t.endswith("}"):
                continue
            if t != c:
                return False
        return True


# ---------------------------------------------------------------------------
# 4. Grounding Validator (3-State Logic)
# ---------------------------------------------------------------------------

class GroundingValidator:
    """Validates extracted code claims against an EvidenceCatalog using 3-state logic."""

    @classmethod
    def validate(
        cls,
        claims: List[ClaimItem],
        catalog: EvidenceCatalog,
    ) -> Tuple[List[CodeViolation], List[GroundingFinding], float]:
        """
        Validate claims against catalog.
        
        Returns:
            - hard_violations: Violations for UNSUPPORTED claims where domain evidence exists.
            - findings: Detailed GroundingFinding for all claims (SUPPORTED, UNSUPPORTED, UNKNOWN).
            - grounding_score: 1.0 - (unsupported / max(total, 1)).
        """
        violations: List[CodeViolation] = []
        findings: List[GroundingFinding] = []

        if not claims:
            return violations, findings, 1.0

        unsupported_count = 0

        for claim in claims:
            match = catalog.find_match(claim)

            if match:
                claim.status = "SUPPORTED"
                claim.matched_evidence_id = match.evidence_id
                findings.append(
                    GroundingFinding(
                        claim_type=claim.kind,
                        claim_value=claim.value,
                        status="SUPPORTED",
                        evidence_id=match.evidence_id,
                        message=f"Supported by verified evidence from '{match.source}'",
                        source_file=claim.file_path,
                    )
                )
            else:
                # Check if the catalog has verified evidence for this domain
                domain_exists = catalog.has_domain(claim.kind)

                if domain_exists:
                    # Domain is known, but this claim is NOT supported -> UNSUPPORTED (Hallucination)
                    claim.status = "UNSUPPORTED"
                    unsupported_count += 1

                    violation_code, err_msg, suggestion = cls._build_violation_details(claim, catalog)
                    violations.append(
                        CodeViolation(
                            code=violation_code,
                            file_path=claim.file_path,
                            line_number=claim.line_number,
                            message=err_msg,
                            severity="error",
                            suggestion=suggestion,
                        )
                    )
                    findings.append(
                        GroundingFinding(
                            claim_type=claim.kind,
                            claim_value=claim.value,
                            status="UNSUPPORTED",
                            evidence_id=None,
                            message=err_msg,
                            source_file=claim.file_path,
                        )
                    )
                else:
                    # Insufficient domain knowledge in catalog -> UNKNOWN (Do not falsely reject)
                    claim.status = "UNKNOWN"
                    findings.append(
                        GroundingFinding(
                            claim_type=claim.kind,
                            claim_value=claim.value,
                            status="UNKNOWN",
                            evidence_id=None,
                            message=f"No authoritative evidence in project catalog for domain '{claim.kind}'.",
                            source_file=claim.file_path,
                        )
                    )

        total_claims = len(claims)
        grounding_score = max(0.0, 1.0 - (unsupported_count / max(total_claims, 1)))

        return violations, findings, round(grounding_score, 4)

    @classmethod
    def _build_violation_details(
        cls,
        claim: ClaimItem,
        catalog: EvidenceCatalog,
    ) -> Tuple[CodeViolationCode, str, str]:
        """Construct descriptive violation message and repair suggestion with available evidence."""
        if claim.kind == "api_endpoint":
            available = [e.value for e in catalog.get_items("api_endpoint")[:5]]
            msg = f"API endpoint '{claim.value}' contradicts project evidence catalog."
            sug = f"Use verified endpoints supported by the project: {available}"
            return CodeViolationCode.UNSUPPORTED_API_ENDPOINT, msg, sug

        elif claim.kind == "ui_selector":
            available = [e.value for e in catalog.get_items("ui_selector")[:5]]
            msg = f"UI selector '{claim.value}' contradicts verified component selectors."
            sug = f"Use verified selectors: {available}"
            return CodeViolationCode.UNSUPPORTED_UI_SELECTOR, msg, sug

        elif claim.kind == "target_symbol":
            available = [e.value for e in catalog.get_items("target_symbol")[:5]]
            msg = f"Referenced symbol '{claim.value}' does not exist in target codebase or module exports."
            sug = f"Import and invoke verified symbols from target package: {available}"
            return CodeViolationCode.HALLUCINATED_SYMBOL, msg, sug

        else:
            msg = f"Claim '{claim.value}' of kind '{claim.kind}' is unsupported by project evidence."
            sug = "Align implementation with verified codebase entities."
            return CodeViolationCode.HALLUCINATED_SYMBOL, msg, sug
