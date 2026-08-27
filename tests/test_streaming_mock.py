import asyncio
import json
import unittest
from unittest.mock import patch, AsyncMock
from app.mcp_server import _fetch_streaming_results, search_knowledge, query_knowledge


class TestStreamingEndToEnd(unittest.IsolatedAsyncioTestCase):
    @patch("httpx.AsyncClient")
    async def test_streaming_results_parsing(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200

        chunk_obj = {"chunk_id": "c101", "content": "class AuthUser:\n    subscription_tier: str", "final_score": 0.92, "source_id": "auth.py"}
        sse_lines = [
            "event: query_decomposition",
            'data: {"query_chunks": [{"text": "auth jwt", "intent": "entity_lookup", "weight": 1.0}], "decomposition_time_ms": 12.5}',
            "",
            "event: chunk_result",
            f"data: {json.dumps(chunk_obj)}",
            "",
            "event: done",
            'data: {"total_results": 1, "unique_sources": 1, "total_time_ms": 45.0}',
            "",
        ]

        async def fake_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response.aiter_lines = fake_aiter_lines
        class AsyncContextManagerMock:
            def __init__(self, response):
                self.response = response

            async def __aenter__(self):
                return self.response

            async def __aexit__(self, exc_type, exc, tb):
                pass

        from unittest.mock import MagicMock
        mock_client.stream = MagicMock(return_value=AsyncContextManagerMock(mock_response))
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        req_dict = {"intent": "how does auth work", "keywords": ["auth", "jwt"], "limit": 10}
        result = await _fetch_streaming_results(req_dict, "req-123")

        self.assertIsNotNone(result)
        self.assertIn("[RESULTS] 1 found", result)
        self.assertIn("[QUERY PLAN] Decomposed into 1 search queries", result)
        self.assertIn("Chunk | auth.py | score=0.920", result)
        self.assertIn("class AuthUser:", result)

    @patch("app.mcp_server._fetch_streaming_results")
    async def test_query_knowledge_alias(self, mock_fetch):
        mock_fetch.return_value = "[RESULTS] 1 found\nChunk | test.py | score=1.0\ncode"
        res = await query_knowledge(intent="test intent", keywords=["test"], limit=5, stream=True)
        self.assertIn("[RESULTS] 1 found", res)


if __name__ == "__main__":
    unittest.main()
