"""Unit tests for Zhipu AI (GLM-4) client and LLMManager integration."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from testteller.core.llm.zhipu_client import ZhipuClient
from testteller.core.llm.llm_manager import LLMManager


def test_zhipu_client_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="No API key found for Zhipu/GLM"):
        ZhipuClient()


def test_zhipu_client_loads_from_env(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_zhipu_key_123")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    client = ZhipuClient()
    assert client.api_key == "test_zhipu_key_123"
    assert client.provider_name == "zhipu"
    assert client.generation_model == "glm-4-flash"
    assert client.embedding_model == "embedding-3"
    assert "bigmodel.cn" in client.base_url


def test_zhipu_client_loads_from_glm_key(monkeypatch):
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.setenv("GLM_API_KEY", "test_glm_key_456")
    client = ZhipuClient()
    assert client.api_key == "test_glm_key_456"


def test_zhipu_client_custom_base_url(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    monkeypatch.setenv("ZHIPU_BASE_URL", "https://custom.zhipu.endpoint/v4/")
    client = ZhipuClient()
    assert client.base_url == "https://custom.zhipu.endpoint/v4/"


def test_zhipu_client_generate_text_sync(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    client = ZhipuClient(generation_model="glm-4")

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "def test_hello(): assert True"
    mock_resp.choices = [mock_choice]

    client.client.chat.completions.create = MagicMock(return_value=mock_resp)

    res = client.generate_text("Generate a test")
    assert "def test_hello()" in res
    client.client.chat.completions.create.assert_called_once()
    call_args = client.client.chat.completions.create.call_args[1]
    assert call_args["model"] == "glm-4"


@pytest.mark.asyncio
async def test_zhipu_client_generate_text_async(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    client = ZhipuClient(generation_model="glm-4-plus")

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "def test_async(): assert 1 == 1"
    mock_resp.choices = [mock_choice]

    client.async_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    res = await client.generate_text_async("Generate async test")
    assert "def test_async()" in res
    client.async_client.chat.completions.create.assert_awaited_once()


def test_zhipu_client_get_embeddings_sync(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    client = ZhipuClient()

    mock_resp = MagicMock()
    d1 = MagicMock(embedding=[0.1, 0.2, 0.3])
    d2 = MagicMock(embedding=[0.4, 0.5, 0.6])
    mock_resp.data = [d1, d2]

    client.client.embeddings.create = MagicMock(return_value=mock_resp)

    embs = client.get_embeddings_sync(["doc1", "doc2"])
    assert len(embs) == 2
    assert embs[0] == [0.1, 0.2, 0.3]
    assert embs[1] == [0.4, 0.5, 0.6]


def test_llm_manager_infers_zhipu_from_glm_model(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    mgr = LLMManager(generation_model="glm-4")
    assert mgr.provider == "zhipu"
    assert isinstance(mgr.client, ZhipuClient)
    assert mgr.client.generation_model == "glm-4"


def test_llm_manager_infers_zhipu_from_glm_flash_model(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    mgr = LLMManager(generation_model="glm-4-flash")
    assert mgr.provider == "zhipu"
    assert isinstance(mgr.client, ZhipuClient)
    assert mgr.client.generation_model == "glm-4-flash"


def test_llm_manager_explicit_zhipu_provider(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    mgr = LLMManager(provider="zhipu", generation_model="glm-4-air")
    assert mgr.provider == "zhipu"
    assert mgr.client.generation_model == "glm-4-air"


def test_llm_manager_explicit_glm_alias(monkeypatch):
    monkeypatch.setenv("ZHIPU_API_KEY", "test_key")
    mgr = LLMManager(provider="glm", generation_model="glm-4")
    assert mgr.provider == "zhipu"


def test_llm_manager_missing_zhipu_key_fails_fast(monkeypatch):
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ZHIPU_API_KEY"):
        LLMManager(generation_model="glm-4", allow_fallback=False)
