"""Offline tests for the deterministic-first hybrid retrieval layer."""

import asyncio
import tempfile
import unittest

from testteller.core.retrieval.hybrid_retriever import HybridRetriever
from testteller.core.retrieval.local_index import LocalIndex


class FakeVectorStore:
    def __init__(self):
        self.calls = 0

    def query_similar(self, query_text, n_results=5):
        self.calls += 1
        return {
            "ids": [["vector-1"]],
            "documents": [["Semantic context for order failure handling."]],
            "metadatas": [[{"source": "docs/orders.md", "type": "document"}]],
            "distances": [[0.2]],
        }


class TestHybridRetriever(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.index = LocalIndex(self.temp_dir.name)
        self.index.add_documents(
            documents=[
                "Test Case E2E_LOGIN_001\nPOST /api/v1/login\n"
                "class LoginService:\n    def create_session(self): pass\n"
                "token = os.getenv('JWT_SECRET')"
            ],
            metadatas=[{"source": "src/login.py", "type": "code"}],
            ids=["login-chunk-1"],
            collection_name="shop_demo",
        )
        self.vector_store = FakeVectorStore()
        self.retriever = HybridRetriever(self.vector_store, self.index)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_exact_test_id_returns_local_without_embedding(self):
        result = asyncio.run(self.retriever.retrieve("E2E_LOGIN_001", "shop_demo"))
        self.assertEqual("local_exact", result.strategy)
        self.assertFalse(result.embedding_called)
        self.assertEqual(0, self.vector_store.calls)
        self.assertEqual("login-chunk-1", result.documents[0].chunk_id)

    def test_generate_intent_uses_hybrid_even_for_exact_api(self):
        result = asyncio.run(
            self.retriever.retrieve("为 POST /api/v1/login 生成测试用例", "shop_demo")
        )
        self.assertEqual("hybrid", result.strategy)
        self.assertTrue(result.embedding_called)
        self.assertEqual(1, self.vector_store.calls)
        self.assertGreaterEqual(len(result.documents), 1)

    def test_collection_isolation_and_idempotent_upsert(self):
        self.index.add_documents(
            documents=["Test Case E2E_LOGIN_001"],
            metadatas=[{"source": "src/login.py", "type": "code"}],
            ids=["login-chunk-1"],
            collection_name="shop_demo",
        )
        result = asyncio.run(self.retriever.retrieve("E2E_LOGIN_001", "other_project"))
        self.assertEqual("not_found", result.strategy)
        local = self.index.search(self.retriever.query_analyzer.analyze("E2E_LOGIN_001"), "shop_demo")
        self.assertEqual(1, len(local.items))

    def test_clear_removes_local_records(self):
        self.index.clear("shop_demo")
        result = asyncio.run(self.retriever.retrieve("E2E_LOGIN_001", "shop_demo"))
        self.assertEqual("not_found", result.strategy)


if __name__ == "__main__":
    unittest.main()
