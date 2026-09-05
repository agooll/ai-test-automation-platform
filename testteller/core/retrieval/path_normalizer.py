"""Normalization helpers for API paths and API method/path keys."""

import re


def normalize_api_path(path: str) -> str:
    """Normalize concrete path parameters so route variants share an index key."""
    value = path.strip().split("?", 1)[0]
    value = re.sub(r"//+", "/", value)
    value = re.sub(r"/:(?:[A-Za-z_]\w*)", "/{id}", value)
    value = re.sub(r"/\d+(?=/|$)", "/{id}", value)
    value = re.sub(r"/[0-9a-fA-F]{8,}(?=/|$)", "/{id}", value)
    return value.rstrip("/") or "/"


def api_key(method: str, path: str) -> str:
    return f"{method.upper()}:{normalize_api_path(path)}"
