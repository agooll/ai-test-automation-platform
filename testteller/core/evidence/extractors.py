"""Deterministic Evidence Extractors for Python AST and OpenAPI specifications (Stage 5.2)."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

from .ids import (
    compute_chunk_id,
    compute_content_hash,
    compute_evidence_id,
    compute_source_id,
    normalize_endpoint_path,
    normalize_evidence_value,
    normalize_relative_path,
)
from .models import EvidenceRecord, TrustLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Python AST Evidence Extractor
# ---------------------------------------------------------------------------

class PythonASTEvidenceExtractor:
    """Authoritative T0 extractor parsing Python AST without LLM hallucinations."""

    HTTP_DECORATOR_METHODS: Set[str] = {
        "get", "post", "put", "delete", "patch", "options", "head"
    }

    def __init__(self, extractor_version: str = "1.0.0"):
        self.extractor_version = extractor_version

    def extract_from_file(
        self,
        file_path: Path | str,
        module_prefix: str = "",
        repository: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> List[EvidenceRecord]:
        """Parse a Python source file and extract authoritative evidence records."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return []
        return self.extract_from_code(
            code=content,
            file_path=str(path),
            module_prefix=module_prefix,
            repository=repository,
            commit_sha=commit_sha,
        )

    def extract_from_code(
        self,
        code: str,
        file_path: str,
        module_prefix: str = "",
        repository: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> List[EvidenceRecord]:
        """Parse Python source code AST and return verified EvidenceRecords."""
        try:
            tree = ast.parse(code, filename=file_path)
        except Exception as exc:
            logger.warning("Failed to parse Python AST for %s: %s", file_path, exc)
            return []

        norm_path = normalize_relative_path(file_path)
        source_id = compute_source_id(repository, commit_sha, norm_path)
        code_lines = code.splitlines(keepends=True)

        records: List[EvidenceRecord] = []

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                records.extend(
                    self._extract_class(node, code_lines, norm_path, source_id, module_prefix, repository, commit_sha)
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                records.extend(
                    self._extract_function(node, code_lines, norm_path, source_id, module_prefix, repository, commit_sha)
                )

        # Walk entire AST for config / env usage
        records.extend(
            self._extract_config_lookups(tree, code_lines, norm_path, source_id, repository, commit_sha)
        )

        return records

    def _extract_class(
        self,
        node: ast.ClassDef,
        code_lines: List[str],
        file_path: str,
        source_id: str,
        module_prefix: str,
        repository: Optional[str],
        commit_sha: Optional[str],
    ) -> List[EvidenceRecord]:
        records: List[EvidenceRecord] = []
        class_name = node.name
        qname = f"{module_prefix}.{class_name}" if module_prefix else class_name

        line_start = node.lineno
        line_end = getattr(node, "end_lineno", line_start)
        chunk_lines = code_lines[line_start - 1 : line_end]
        c_hash = compute_content_hash("".join(chunk_lines))
        chunk_id = compute_chunk_id(source_id, line_start, line_end, c_hash)

        # 1. Class target_symbol
        ev_id = compute_evidence_id("target_symbol", qname, chunk_id)
        records.append(
            EvidenceRecord(
                evidence_id=ev_id,
                kind="target_symbol",
                value=qname,
                source_id=source_id,
                source_path=file_path,
                source_chunk_id=chunk_id,
                line_start=line_start,
                line_end=line_end,
                commit_sha=commit_sha,
                content_hash=c_hash,
                extractor="ast_extractor",
                extractor_version=self.extractor_version,
                trust_level=TrustLevel.T0_AUTHORITATIVE,
                metadata={"symbol_type": "class", "short_name": class_name},
            )
        )
        if module_prefix:
            ev_short = compute_evidence_id("target_symbol", class_name, chunk_id)
            records.append(
                EvidenceRecord(
                    evidence_id=ev_short,
                    kind="target_symbol",
                    value=class_name,
                    source_id=source_id,
                    source_path=file_path,
                    source_chunk_id=chunk_id,
                    line_start=line_start,
                    line_end=line_end,
                    commit_sha=commit_sha,
                    content_hash=c_hash,
                    extractor="ast_extractor",
                    extractor_version=self.extractor_version,
                    trust_level=TrustLevel.T0_AUTHORITATIVE,
                    metadata={"symbol_type": "class", "full_qname": qname},
                )
            )

        # 2. Methods and route decorators on methods
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_name = item.name
                m_start = item.lineno
                m_end = getattr(item, "end_lineno", m_start)
                m_chunk_lines = code_lines[m_start - 1 : m_end]
                m_hash = compute_content_hash("".join(m_chunk_lines))
                m_chunk_id = compute_chunk_id(source_id, m_start, m_end, m_hash)

                method_qname = f"{qname}.{method_name}"
                ev_m_id = compute_evidence_id("target_symbol", method_qname, m_chunk_id)
                records.append(
                    EvidenceRecord(
                        evidence_id=ev_m_id,
                        kind="target_symbol",
                        value=method_qname,
                        source_id=source_id,
                        source_path=file_path,
                        source_chunk_id=m_chunk_id,
                        line_start=m_start,
                        line_end=m_end,
                        commit_sha=commit_sha,
                        content_hash=m_hash,
                        extractor="ast_extractor",
                        extractor_version=self.extractor_version,
                        trust_level=TrustLevel.T0_AUTHORITATIVE,
                        metadata={"symbol_type": "method", "class_name": class_name},
                    )
                )

                # Check if method has route decorators
                route_records = self._extract_route_decorators(
                    item, m_chunk_id, m_hash, file_path, source_id, commit_sha, m_start, m_end
                )
                records.extend(route_records)

            # 3. Model fields (Pydantic / dataclass annotations: `name: str`)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                field_qname = f"{class_name}.{field_name}"
                f_start = item.lineno
                f_end = getattr(item, "end_lineno", f_start)
                f_hash = compute_content_hash("".join(code_lines[f_start - 1 : f_end]))
                f_chunk_id = compute_chunk_id(source_id, f_start, f_end, f_hash)

                ev_f_id = compute_evidence_id("model_field", field_qname, f_chunk_id)
                type_ann = ast.unparse(item.annotation) if hasattr(ast, "unparse") else "Any"
                records.append(
                    EvidenceRecord(
                        evidence_id=ev_f_id,
                        kind="model_field",
                        value=field_qname,
                        source_id=source_id,
                        source_path=file_path,
                        source_chunk_id=f_chunk_id,
                        line_start=f_start,
                        line_end=f_end,
                        commit_sha=commit_sha,
                        content_hash=f_hash,
                        extractor="ast_extractor",
                        extractor_version=self.extractor_version,
                        trust_level=TrustLevel.T0_AUTHORITATIVE,
                        metadata={"class_name": class_name, "field_name": field_name, "annotation": type_ann},
                    )
                )

        return records

    def _extract_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        code_lines: List[str],
        file_path: str,
        source_id: str,
        module_prefix: str,
        repository: Optional[str],
        commit_sha: Optional[str],
    ) -> List[EvidenceRecord]:
        records: List[EvidenceRecord] = []
        fn_name = node.name
        qname = f"{module_prefix}.{fn_name}" if module_prefix else fn_name

        line_start = node.lineno
        line_end = getattr(node, "end_lineno", line_start)
        chunk_lines = code_lines[line_start - 1 : line_end]
        c_hash = compute_content_hash("".join(chunk_lines))
        chunk_id = compute_chunk_id(source_id, line_start, line_end, c_hash)

        # 1. Function target_symbol
        ev_id = compute_evidence_id("target_symbol", qname, chunk_id)
        records.append(
            EvidenceRecord(
                evidence_id=ev_id,
                kind="target_symbol",
                value=qname,
                source_id=source_id,
                source_path=file_path,
                source_chunk_id=chunk_id,
                line_start=line_start,
                line_end=line_end,
                commit_sha=commit_sha,
                content_hash=c_hash,
                extractor="ast_extractor",
                extractor_version=self.extractor_version,
                trust_level=TrustLevel.T0_AUTHORITATIVE,
                metadata={"symbol_type": "function"},
            )
        )
        if module_prefix:
            ev_short = compute_evidence_id("target_symbol", fn_name, chunk_id)
            records.append(
                EvidenceRecord(
                    evidence_id=ev_short,
                    kind="target_symbol",
                    value=fn_name,
                    source_id=source_id,
                    source_path=file_path,
                    source_chunk_id=chunk_id,
                    line_start=line_start,
                    line_end=line_end,
                    commit_sha=commit_sha,
                    content_hash=c_hash,
                    extractor="ast_extractor",
                    extractor_version=self.extractor_version,
                    trust_level=TrustLevel.T0_AUTHORITATIVE,
                    metadata={"symbol_type": "function", "full_qname": qname},
                )
            )

        # 2. Check route decorators (FastAPI/Flask)
        route_records = self._extract_route_decorators(
            node, chunk_id, c_hash, file_path, source_id, commit_sha, line_start, line_end
        )
        records.extend(route_records)

        return records

    def _extract_route_decorators(
        self,
        fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
        chunk_id: str,
        content_hash: str,
        file_path: str,
        source_id: str,
        commit_sha: Optional[str],
        line_start: int,
        line_end: int,
    ) -> List[EvidenceRecord]:
        records: List[EvidenceRecord] = []
        for dec in fn_node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue

            method: Optional[str] = None
            path: Optional[str] = None

            # Pattern 1: @app.get("/users"), @router.post("/items")
            if isinstance(dec.func, ast.Attribute):
                attr_name = dec.func.attr.lower()
                if attr_name in self.HTTP_DECORATOR_METHODS:
                    method = attr_name.upper()
                    # First argument is path
                    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                        path = dec.args[0].value
                # Pattern 2: @app.route("/users", methods=["GET", "POST"])
                elif attr_name == "route":
                    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                        path = dec.args[0].value
                    # Check methods kwarg
                    methods_found = []
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    methods_found.append(elt.value.upper())
                    if path:
                        for m in (methods_found or ["GET"]):
                            norm_endpoint = f"{m} {normalize_endpoint_path(path)}"
                            ev_id = compute_evidence_id("api_endpoint", norm_endpoint, chunk_id)
                            records.append(
                                EvidenceRecord(
                                    evidence_id=ev_id,
                                    kind="api_endpoint",
                                    value=norm_endpoint,
                                    source_id=source_id,
                                    source_path=file_path,
                                    source_chunk_id=chunk_id,
                                    line_start=line_start,
                                    line_end=line_end,
                                    commit_sha=commit_sha,
                                    content_hash=content_hash,
                                    extractor="ast_extractor",
                                    extractor_version=self.extractor_version,
                                    trust_level=TrustLevel.T0_AUTHORITATIVE,
                                    metadata={"framework": "flask/generic", "handler": fn_node.name},
                                )
                            )
                        continue

            if method and path:
                norm_endpoint = f"{method} {normalize_endpoint_path(path)}"
                ev_id = compute_evidence_id("api_endpoint", norm_endpoint, chunk_id)
                records.append(
                    EvidenceRecord(
                        evidence_id=ev_id,
                        kind="api_endpoint",
                        value=norm_endpoint,
                        source_id=source_id,
                        source_path=file_path,
                        source_chunk_id=chunk_id,
                        line_start=line_start,
                        line_end=line_end,
                        commit_sha=commit_sha,
                        content_hash=content_hash,
                        extractor="ast_extractor",
                        extractor_version=self.extractor_version,
                        trust_level=TrustLevel.T0_AUTHORITATIVE,
                        metadata={"framework": "fastapi", "handler": fn_node.name},
                    )
                )

        return records

    def _extract_config_lookups(
        self,
        tree: ast.AST,
        code_lines: List[str],
        file_path: str,
        source_id: str,
        repository: Optional[str],
        commit_sha: Optional[str],
    ) -> List[EvidenceRecord]:
        records: List[EvidenceRecord] = []
        for node in ast.walk(tree):
            key: Optional[str] = None
            line_no = getattr(node, "lineno", 1)

            # os.getenv("FOO") or os.environ.get("FOO")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("getenv", "get") and node.args:
                    if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        key = node.args[0].value
            # os.environ["FOO"]
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
                if node.value.attr == "environ" and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    key = node.slice.value

            if key and len(key) >= 2:
                chunk_line = code_lines[line_no - 1] if line_no <= len(code_lines) else key
                c_hash = compute_content_hash(chunk_line)
                chunk_id = compute_chunk_id(source_id, line_no, line_no, c_hash)
                ev_id = compute_evidence_id("config", key, chunk_id)
                records.append(
                    EvidenceRecord(
                        evidence_id=ev_id,
                        kind="config",
                        value=key,
                        source_id=source_id,
                        source_path=file_path,
                        source_chunk_id=chunk_id,
                        line_start=line_no,
                        line_end=line_no,
                        commit_sha=commit_sha,
                        content_hash=c_hash,
                        extractor="ast_extractor",
                        extractor_version=self.extractor_version,
                        trust_level=TrustLevel.T0_AUTHORITATIVE,
                        metadata={"config_type": "env_var"},
                    )
                )

        return records


# ---------------------------------------------------------------------------
# 2. OpenAPI Specification Evidence Extractor
# ---------------------------------------------------------------------------

class OpenAPIEvidenceExtractor:
    """Authoritative T0 extractor parsing OpenAPI JSON/YAML specifications."""

    SUPPORTED_METHODS: Set[str] = {"get", "post", "put", "delete", "patch", "options", "head"}

    def __init__(self, extractor_version: str = "1.0.0"):
        self.extractor_version = extractor_version

    def extract_from_file(
        self,
        file_path: Path | str,
        repository: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> List[EvidenceRecord]:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Failed to read OpenAPI spec %s: %s", path, exc)
            return []
        return self.extract_from_spec(
            spec_content=content,
            file_path=str(path),
            repository=repository,
            commit_sha=commit_sha,
        )

    def extract_from_spec(
        self,
        spec_content: str | dict,
        file_path: str = "openapi.yaml",
        repository: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> List[EvidenceRecord]:
        if isinstance(spec_content, dict):
            spec = spec_content
            content_str = json.dumps(spec)
        else:
            content_str = spec_content
            try:
                spec = json.loads(spec_content)
            except Exception:
                try:
                    spec = yaml.safe_load(spec_content) or {}
                except Exception as exc:
                    logger.warning("Failed to parse OpenAPI YAML/JSON: %s", exc)
                    return []

        norm_path = normalize_relative_path(file_path)
        source_id = compute_source_id(repository, commit_sha, norm_path)
        c_hash = compute_content_hash(content_str)
        chunk_id = compute_chunk_id(source_id, 1, len(content_str.splitlines()) or 1, c_hash)

        records: List[EvidenceRecord] = []
        paths_obj = spec.get("paths", {})
        if isinstance(paths_obj, dict):
            for path_str, path_item in paths_obj.items():
                if not isinstance(path_item, dict):
                    continue
                norm_p = normalize_endpoint_path(path_str)
                for method in self.SUPPORTED_METHODS:
                    op = path_item.get(method)
                    if not isinstance(op, dict):
                        continue
                    m_upper = method.upper()
                    endpoint_val = f"{m_upper} {norm_p}"
                    ev_ep_id = compute_evidence_id("api_endpoint", endpoint_val, chunk_id)
                    records.append(
                        EvidenceRecord(
                            evidence_id=ev_ep_id,
                            kind="api_endpoint",
                            value=endpoint_val,
                            source_id=source_id,
                            source_path=norm_path,
                            source_chunk_id=chunk_id,
                            commit_sha=commit_sha,
                            content_hash=c_hash,
                            extractor="openapi_extractor",
                            extractor_version=self.extractor_version,
                            trust_level=TrustLevel.T0_AUTHORITATIVE,
                            metadata={
                                "operation_id": op.get("operationId", ""),
                                "summary": op.get("summary", ""),
                            },
                        )
                    )

                    # Behavioral contract: response status codes
                    responses = op.get("responses", {})
                    if isinstance(responses, dict):
                        for status_code, resp_obj in responses.items():
                            contract_val = f"{m_upper} {norm_p} -> {status_code}"
                            ev_c_id = compute_evidence_id("behavior_contract", contract_val, chunk_id)
                            records.append(
                                EvidenceRecord(
                                    evidence_id=ev_c_id,
                                    kind="behavior_contract",
                                    value=contract_val,
                                    source_id=source_id,
                                    source_path=norm_path,
                                    source_chunk_id=chunk_id,
                                    commit_sha=commit_sha,
                                    content_hash=c_hash,
                                    extractor="openapi_extractor",
                                    extractor_version=self.extractor_version,
                                    trust_level=TrustLevel.T0_AUTHORITATIVE,
                                    metadata={"status_code": status_code},
                                )
                            )

                    # Security schemes on operation
                    security = op.get("security", spec.get("security", []))
                    if isinstance(security, list):
                        for sec_item in security:
                            if isinstance(sec_item, dict):
                                for sec_scheme in sec_item.keys():
                                    ev_s_id = compute_evidence_id("auth_pattern", sec_scheme, chunk_id)
                                    records.append(
                                        EvidenceRecord(
                                            evidence_id=ev_s_id,
                                            kind="auth_pattern",
                                            value=sec_scheme,
                                            source_id=source_id,
                                            source_path=norm_path,
                                            source_chunk_id=chunk_id,
                                            commit_sha=commit_sha,
                                            content_hash=c_hash,
                                            extractor="openapi_extractor",
                                            extractor_version=self.extractor_version,
                                            trust_level=TrustLevel.T0_AUTHORITATIVE,
                                            metadata={"endpoint": endpoint_val},
                                        )
                                    )

        # Components / Schemas (OpenAPI v3 or Swagger v2)
        schemas = (
            spec.get("components", {}).get("schemas", {})
            if isinstance(spec.get("components"), dict)
            else spec.get("definitions", {})
        )
        if isinstance(schemas, dict):
            for schema_name, schema_def in schemas.items():
                if not isinstance(schema_def, dict):
                    continue
                props = schema_def.get("properties", {})
                if isinstance(props, dict):
                    for prop_name, prop_def in props.items():
                        field_val = f"{schema_name}.{prop_name}"
                        ev_f_id = compute_evidence_id("model_field", field_val, chunk_id)
                        p_type = prop_def.get("type", "any") if isinstance(prop_def, dict) else "any"
                        records.append(
                            EvidenceRecord(
                                evidence_id=ev_f_id,
                                kind="model_field",
                                value=field_val,
                                source_id=source_id,
                                source_path=norm_path,
                                source_chunk_id=chunk_id,
                                commit_sha=commit_sha,
                                content_hash=c_hash,
                                extractor="openapi_extractor",
                                extractor_version=self.extractor_version,
                                trust_level=TrustLevel.T0_AUTHORITATIVE,
                                metadata={
                                    "schema_name": schema_name,
                                    "property": prop_name,
                                    "type": p_type,
                                },
                            )
                        )

        return records
