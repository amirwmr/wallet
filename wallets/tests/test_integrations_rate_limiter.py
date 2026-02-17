from unittest.mock import Mock

from django.test import SimpleTestCase

from wallets.integrations.rate_limiter import (
    NoopRateLimiter,
    RedisTokenBucketRateLimiter,
)


class RateLimiterTests(SimpleTestCase):
    def test_noop_rate_limiter_returns_zero_wait(self):
        limiter = NoopRateLimiter()
        result = limiter.acquire(cost=1)
        self.assertEqual(result.wait_seconds, 0.0)
        self.assertEqual(result.wait_events, 0)

    def test_redis_token_bucket_limiter_waits_then_allows(self):
        redis_client = Mock()
        redis_client.register_script.return_value = Mock(side_effect=[[0, 0], [1, 0]])

        limiter = RedisTokenBucketRateLimiter(
            redis_client=redis_client,
            key="wallet:test",
            max_rps=10,
        )
        result = limiter.acquire(cost=1)

        self.assertEqual(result.wait_events, 1)
