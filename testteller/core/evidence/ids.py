"""Deterministic content-addressed identifier generators for Stage 5 Provenance."""

from __future__ import annotations

import hashlib
from typing import Optional
from urllib.parse import urlparse


def normalize_relative_path(path: str) -> str:
    """Normalize file path to use forward slashes and strip redundant separators."""
    norm = path.replace("\\", "/").strip()
    while "//" in norm:
        norm = norm.replace("//", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    return norm


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of text content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_source_id(
    repository: Optional[str],
    commit_sha: Optional[str],
    relative_path: str,
) -> str:
    """
    Generate deterministic source_id from repository, commit, and relative path.
    source_id = SHA256(repo + commit + relative_path)
    """
    repo_clean = (repository or "").strip()
    commit_clean = (commit_sha or "").strip()
    path_clean = normalize_relative_path(relative_path)
    payload = f"{repo_clean}:{commit_clean}:{path_clean}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_chunk_id(
    source_id: str,
    line_start: int,
    line_end: int,
    content_hash: str,
) -> str:
    """
    Generate deterministic chunk_id from source_id, line range, and content hash.
    chunk_id = SHA256(source_id + line_start + line_end + content_hash)
    """
    payload = f"{source_id}:{line_start}:{line_end}:{content_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_endpoint_path(path_or_url: str) -> str:
    """Extract path component and normalize leading/trailing slashes."""
    if "://" in path_or_url:
        path = urlparse(path_or_url).path
    else:
        path = path_or_url.split("?")[0]
    path = path.strip()
    if not path.startswith("/"):
        path = f"/{path}"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def normalize_evidence_value(kind: str, value: str) -> str:
    """Normalize an evidence value for deterministic hashing and lookups."""
    val = value.strip()
    if kind == "api_endpoint":
        parts = val.split(maxsplit=1)
        if len(parts) == 2:
            method, path = parts[0].upper(), normalize_endpoint_path(parts[1])
            return f"{method} {path}"
        return val.upper()
    elif kind == "ui_selector":
        return val.strip("\"'")
    elif kind == "target_symbol":
        return val.strip()
    elif kind == "config":
        return val.strip()
    elif kind == "model_field":
        return val.strip()
    return val


def compute_evidence_id(
    kind: str,
    normalized_value: str,
    source_chunk_id: str,
) -> str:
    """
    Generate deterministic evidence_id:
    EV-{kind}-{SHA256(kind + normalized_value + source_chunk_id)[:16]}
    """
    norm_val = normalize_evidence_value(kind, normalized_value)
    payload = f"{kind}:{norm_val}:{source_chunk_id}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"EV-{kind}-{digest}"
