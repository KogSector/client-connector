"""
Tests for subscription tier rate limiting, single result compression, and streaming retrieval.
"""

import sys
import unittest

from app.auth import AuthUser, RateLimiter
from app.config import Settings
from app.services.prompt_compressor import PromptCompressor
from app.services.session import ClientSession
from proto import auth_v1_pb2


class TestSubscriptionTierAndStreaming(unittest.TestCase):
    def setUp(self):
        self.compressor = PromptCompressor()
        self.rate_limiter = RateLimiter(
            tier_limits={
                "free": {"per_minute": 3, "burst": 1},
                "pro": {"per_minute": 5, "burst": 2},
                "team": {"per_minute": 10, "burst": 3},
                "enterprise": {"per_minute": 20, "burst": 5},
            }
        )

    def test_rate_limiter_free_tier(self):
        key = "user_free_1"
        self.assertTrue(self.rate_limiter.is_allowed(key, tier="free"))
        self.assertTrue(self.rate_limiter.is_allowed(key, tier="free"))
        self.assertTrue(self.rate_limiter.is_allowed(key, tier="free"))
        # 4th request exceeds free tier limit (3)
        self.assertFalse(self.rate_limiter.is_allowed(key, tier="free"))
        self.assertEqual(self.rate_limiter.get_remaining(key, tier="free"), 0)

    def test_rate_limiter_pro_tier(self):
        key = "user_pro_1"
        for _ in range(5):
            self.assertTrue(self.rate_limiter.is_allowed(key, tier="pro"))
        # 6th request exceeds pro limit (5)
        self.assertFalse(self.rate_limiter.is_allowed(key, tier="pro"))

    def test_rate_limiter_enterprise_tier(self):
        key = "user_ent_1"
        for _ in range(20):
            self.assertTrue(self.rate_limiter.is_allowed(key, tier="enterprise"))
        # 21st request exceeds enterprise limit (20)
        self.assertFalse(self.rate_limiter.is_allowed(key, tier="enterprise"))

    def test_auth_user_tier(self):
        user = AuthUser(
            user_id="usr_123",
            email="test@example.com",
            subscription_tier="team",
        )
        self.assertEqual(user.subscription_tier, "team")
        self.assertEqual(user.user_id, "usr_123")

    def test_client_session_tier_tracking(self):
        session = ClientSession(
            user_id="usr_456",
            subscription_tier="pro",
            rate_limit_remaining=240,
        )
        self.assertEqual(session.subscription_tier, "pro")
        self.assertEqual(session.rate_limit_remaining, 240)
        ctx = session.get_context()
        self.assertEqual(ctx["subscription_tier"], "pro")

    def test_grpc_protobuf_subscription_tier(self):
        token_resp = auth_v1_pb2.ValidateTokenResponse(
            valid=True,
            user_id="sub_789",
            email="dev@confuse.dev",
            subscription_tier="enterprise",
        )
        self.assertEqual(token_resp.subscription_tier, "enterprise")

        api_resp = auth_v1_pb2.ValidateApiKeyResponse(
            valid=True,
            user_id="sub_789",
            email="dev@confuse.dev",
            subscription_tier="pro",
        )
        self.assertEqual(api_resp.subscription_tier, "pro")

    def test_compress_single_result_chunk(self):
        chunk_data = {
            "chunk_id": "c1",
            "content": "def hello():\n    return 'world'",
            "final_score": 0.95,
            "source_id": "repo-123/main.py",
        }
        compressed = self.compressor.compress_single_result(chunk_data)
        self.assertIn("Chunk | repo-123/main.py | score=0.950", compressed)
        self.assertIn("def hello():", compressed)

    def test_compress_single_result_graph_node(self):
        node_data = {
            "type": "Function",
            "id": "app.auth.validate_jwt_token",
            "final_score": 0.88,
            "properties": {"file": "auth.py", "lines": "100-120"},
            "relationships": [{"type": "CALLS", "target": "grpc.validate"}],
            "content": "async def validate_jwt_token(...): ...",
        }
        compressed = self.compressor.compress_single_result(node_data)
        self.assertIn("Node | Function:app.auth.validate_jwt_token", compressed)
        self.assertIn("-> CALLS -> grpc.validate", compressed)


if __name__ == "__main__":
    unittest.main()
