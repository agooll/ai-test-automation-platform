"""Centralized patterns used by local indexing and query analysis."""

import re

TEST_ID_PATTERN = re.compile(r"\b(?:E2E|INT|TECH|MOCK)_[A-Z0-9_]+\b", re.IGNORECASE)
API_PATH_PATTERN = re.compile(r"/(?:api/)?[A-Za-z0-9_./{}:-]+")
HTTP_METHOD_PATTERN = re.compile(
    r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b", re.IGNORECASE
)
PYTHON_CLASS_PATTERN = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
PYTHON_FUNCTION_PATTERN = re.compile(r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)")
JS_TS_FUNCTION_PATTERN = re.compile(r"\b(?:function|const|let|var)\s+([A-Za-z_$]\w*)")
QUALIFIED_SYMBOL_PATTERN = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
DATA_TESTID_PATTERN = re.compile(r'''data-testid\s*=\s*["']([^"']+)["']''', re.IGNORECASE)
ENV_GETENV_PATTERN = re.compile(r'''os\.(?:getenv|environ\[)\s*\(?\s*["']([A-Z][A-Z0-9_]+)["']''')
ENV_PROCESS_PATTERN = re.compile(r"\bprocess\.env\.([A-Z][A-Z0-9_]+)\b")
ENV_TEMPLATE_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]+)\}")
FILE_NAME_PATTERN = re.compile(r"\b[A-Za-z0-9_.-]+\.(?:py|js|ts|java|json|ya?ml|md|txt|xml)\b")
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}")

FRAMEWORKS = {"pytest", "playwright", "selenium", "jest", "mocha", "cypress", "junit", "testng"}
ENV_EXCLUDE_WORDS = {
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "HTTP", "HTTPS",
    "JWT", "JSON", "API", "E2E", "INT", "TECH", "MOCK",
}
