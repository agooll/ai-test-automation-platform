"""
Zhipu AI (GLM-4) API client implementation using OpenAI-compatible endpoint.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

import openai

from testteller.config import settings
from .base_client import BaseLLMClient
from ..constants import (
    DEFAULT_ZHIPU_GENERATION_MODEL,
    DEFAULT_ZHIPU_EMBEDDING_MODEL,
    DEFAULT_ZHIPU_BASE_URL,
    ENV_ZHIPU_API_KEY,
    ENV_GLM_API_KEY,
    ENV_ZHIPU_BASE_URL,
)
from ..utils.retry_helpers import api_retry_async, api_retry_sync

logger = logging.getLogger(__name__)


class ZhipuClient(BaseLLMClient):
    """Client for interacting with Zhipu AI (GLM-4) via its official OpenAI-compatible API."""

    def __init__(
        self,
        generation_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self._custom_api_key = api_key
        self._custom_base_url = base_url
        super().__init__("zhipu")

        if generation_model:
            self.generation_model = generation_model
        if embedding_model:
            self.embedding_model = embedding_model

        resolved_base_url = self._get_base_url()
        self.client = openai.OpenAI(api_key=self.api_key, base_url=resolved_base_url)
        self.async_client = openai.AsyncOpenAI(api_key=self.api_key, base_url=resolved_base_url)
        self.base_url = resolved_base_url

        logger.info(
            "Initialized Zhipu (GLM-4) client with base_url '%s', generation model '%s', embedding model '%s'",
            self.base_url,
            self.generation_model,
            self.embedding_model,
        )

    def _get_api_key(self) -> str:
        """Get API key from custom param, settings, ZHIPU_API_KEY or GLM_API_KEY."""
        if self._custom_api_key:
            return self._custom_api_key

        try:
            if settings and settings.api_keys:
                api_key = getattr(settings.api_keys, "zhipu_api_key", None)
                if api_key:
                    return api_key
        except Exception as e:
            logger.debug("Could not get Zhipu API key from settings: %s", e)

        # Check environment variables
        for env_var in (ENV_ZHIPU_API_KEY, ENV_GLM_API_KEY):
            val = os.getenv(env_var)
            if val and val.strip():
                return val.strip()

        raise ValueError(
            f"No API key found for Zhipu/GLM. Please set {ENV_ZHIPU_API_KEY} (or {ENV_GLM_API_KEY}) in your .env or environment."
        )

    def _get_base_url(self) -> str:
        """Get Zhipu AI OpenAI-compatible base URL."""
        if self._custom_base_url:
            return self._custom_base_url

        env_url = os.getenv(ENV_ZHIPU_BASE_URL)
        if env_url and env_url.strip():
            return env_url.strip()

        try:
            if settings and settings.llm and getattr(settings.llm, "zhipu_base_url", None):
                return settings.llm.zhipu_base_url
        except Exception:
            pass

        return DEFAULT_ZHIPU_BASE_URL

    def _get_env_key_name(self) -> str:
        return ENV_ZHIPU_API_KEY

    def _get_default_models(self) -> tuple[str, str]:
        return DEFAULT_ZHIPU_GENERATION_MODEL, DEFAULT_ZHIPU_EMBEDDING_MODEL

    @api_retry_async
    async def get_embedding_async(self, text: str) -> List[float]:
        """Get embeddings for text asynchronously."""
        if not text or not text.strip():
            return None
        try:
            response = await self.async_client.embeddings.create(
                model=self.embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("Error generating Zhipu embedding async for text '%s...': %s", text[:50], e)
            return None

    @api_retry_sync
    def get_embedding_sync(self, text: str) -> List[float]:
        """Get embeddings for text synchronously."""
        if not text or not text.strip():
            return None
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("Error generating Zhipu embedding sync for text '%s...': %s", text[:50], e)
            return None

    @api_retry_sync
    def get_embeddings_sync(self, texts: list[str]) -> list[list[float] | None]:
        """Get embeddings for a list of texts synchronously."""
        if not texts:
            return []
        try:
            processed_texts = [t if t.strip() else " " for t in texts]
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=processed_texts,
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            logger.error("Error generating Zhipu sync embeddings for batch of %d texts: %s", len(texts), e)
            return [None] * len(texts)

    @api_retry_async
    async def generate_text_async(self, prompt: str, **kwargs) -> str:
        """Generate text using GLM-4 asynchronously."""
        try:
            temperature = kwargs.get("temperature", 0.7)
            response = await self.async_client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("Error generating text with Zhipu GLM async: %s", e)
            raise

    @api_retry_sync
    def generate_text(self, prompt: str, **kwargs) -> str:
        """Generate text using GLM-4 synchronously."""
        try:
            temperature = kwargs.get("temperature", 0.7)
            response = self.client.chat.completions.create(
                model=self.generation_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("Error generating text with Zhipu GLM: %s", e)
            raise
