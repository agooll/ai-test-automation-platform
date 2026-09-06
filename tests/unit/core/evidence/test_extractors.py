"""Unit tests for Stage 5.2 Deterministic Evidence Extractors (Python AST and OpenAPI)."""

import json
import pytest
from testteller.core.evidence.extractors import (
    PythonASTEvidenceExtractor,
    OpenAPIEvidenceExtractor,
)
from testteller.core.evidence.models import TrustLevel


@pytest.mark.unit
def test_python_ast_extractor_fastapi_and_flask():
    """Extract FastAPI and Flask routes deterministically."""
    code = """
from fastapi import FastAPI, APIRouter
from flask import Flask

app = FastAPI()
router = APIRouter()
flask_app = Flask(__name__)

@app.get("/api/v1/users/{user_id}")
def get_user(user_id: int):
    return {"id": user_id}

@router.post("/auth/login")
async def login():
    return {"token": "xyz"}

@flask_app.route("/healthz", methods=["GET", "HEAD"])
def health():
    return "ok"
"""
    extractor = PythonASTEvidenceExtractor()
    records = extractor.extract_from_code(
        code=code,
        file_path="src/api/routes.py",
        module_prefix="src.api",
        commit_sha="0842b24",
    )

    api_records = [r for r in records if r.kind == "api_endpoint"]
    values = [r.value for r in api_records]

    assert "GET /api/v1/users/{user_id}" in values
    assert "POST /auth/login" in values
    assert "GET /healthz" in values
    assert "HEAD /healthz" in values

    for r in api_records:
        assert r.trust_level == TrustLevel.T0_AUTHORITATIVE
        assert r.extractor == "ast_extractor"
        assert r.commit_sha == "0842b24"
        assert r.line_start is not None
        assert r.evidence_id.startswith("EV-api_endpoint-")


@pytest.mark.unit
def test_python_ast_extractor_classes_methods_and_pydantic():
    """Extract classes, methods, and Pydantic model fields with types."""
    code = """
from pydantic import BaseModel

class UserCreate(BaseModel):
    email: str
    username: str
    is_active: bool = True

class UserService:
    def create_user(self, user: UserCreate):
        return True

    def _internal_helper(self):
        pass
"""
    extractor = PythonASTEvidenceExtractor()
    records = extractor.extract_from_code(
        code=code,
        file_path="src/services/user.py",
        module_prefix="services.user",
        commit_sha="0842b24",
    )

    symbols = [r.value for r in records if r.kind == "target_symbol"]
    fields = [r.value for r in records if r.kind == "model_field"]

    assert "services.user.UserCreate" in symbols
    assert "UserCreate" in symbols
    assert "services.user.UserService" in symbols
    assert "UserService" in symbols
    assert "services.user.UserService.create_user" in symbols

    assert "UserCreate.email" in fields
    assert "UserCreate.username" in fields
    assert "UserCreate.is_active" in fields

    field_record = next(r for r in records if r.value == "UserCreate.email")
    assert field_record.metadata.get("annotation") == "str"


@pytest.mark.unit
def test_python_ast_extractor_configs():
    """Extract environment variable usages from os.getenv and os.environ."""
    code = """
import os

def init_app():
    secret = os.getenv("JWT_SECRET_KEY")
    api_key = os.environ.get("OPENAI_API_KEY")
    port = os.environ["PORT"]
"""
    extractor = PythonASTEvidenceExtractor()
    records = extractor.extract_from_code(
        code=code,
        file_path="src/config.py",
        commit_sha="0842b24",
    )

    configs = [r.value for r in records if r.kind == "config"]
    assert "JWT_SECRET_KEY" in configs
    assert "OPENAI_API_KEY" in configs
    assert "PORT" in configs


@pytest.mark.unit
def test_openapi_extractor_json_and_yaml():
    """Extract endpoints, status contracts, auth patterns, and schemas from OpenAPI."""
    openapi_spec = {
        "openapi": "3.0.0",
        "paths": {
            "/api/v2/orders": {
                "post": {
                    "operationId": "createOrder",
                    "responses": {
                        "201": {"description": "Order created"},
                        "400": {"description": "Bad Request"},
                    },
                    "security": [{"BearerAuth": []}],
                }
            }
        },
        "components": {
            "schemas": {
                "OrderRequest": {
                    "properties": {
                        "item_id": {"type": "string"},
                        "quantity": {"type": "integer"},
                    }
                }
            }
        },
    }

    extractor = OpenAPIEvidenceExtractor()
    records = extractor.extract_from_spec(
        spec_content=openapi_spec,
        file_path="docs/openapi.json",
        commit_sha="0842b24",
    )

    endpoints = [r.value for r in records if r.kind == "api_endpoint"]
    contracts = [r.value for r in records if r.kind == "behavior_contract"]
    auth = [r.value for r in records if r.kind == "auth_pattern"]
    fields = [r.value for r in records if r.kind == "model_field"]

    assert "POST /api/v2/orders" in endpoints
    assert "POST /api/v2/orders -> 201" in contracts
    assert "POST /api/v2/orders -> 400" in contracts
    assert "BearerAuth" in auth
    assert "OrderRequest.item_id" in fields
    assert "OrderRequest.quantity" in fields

    for r in records:
        assert r.trust_level == TrustLevel.T0_AUTHORITATIVE
        assert r.extractor == "openapi_extractor"
        assert r.commit_sha == "0842b24"
