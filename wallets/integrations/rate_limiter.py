import logging
import time
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)


_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local capacity = 1.0

local tokens = tonumber(redis.call("HGET", key, "tokens"))
local ts_ms = tonumber(redis.call("HGET", key, "ts_ms"))

if tokens == nil then
  tokens = capacity
end
if ts_ms == nil then
  ts_ms = now_ms
end

local elapsed = math.max(0, now_ms - ts_ms) / 1000.0
tokens = math.min(capacity, tokens + elapsed * rate)

if tokens >= cost then
  tokens = tokens - cost
  redis.call("HSET", key, "tokens", tokens, "ts_ms", now_ms)
  return {1, 0}
end

local wait_seconds = (cost - tokens) / rate
redis.call("HSET", key, "tokens", tokens, "ts_ms", now_ms)
return {0, wait_seconds}
"""


class RateLimiterUnavailable(Exception):
    pass


class BaseRateLimiter:
    def acquire(self, *, cost=1):
        raise NotImplementedError


class NoopRateLimiter(BaseRateLimiter):
    def acquire(self, *, cost=1):
        return AcquireResult(wait_seconds=0.0, wait_events=0)


@dataclass(frozen=True)
class AcquireResult:
    wait_seconds: float
    wait_events: int


class RedisTokenBucketRateLimiter(BaseRateLimiter):
    def __init__(self, *, redis_client, key, max_rps):
        if max_rps <= 0:
            raise ValueError("max_rps must be > 0")

        self.redis_client = redis_client
        self.key = key
        self.max_rps = float(max_rps)
        self._script = self.redis_client.register_script(_TOKEN_BUCKET_LUA)

    def acquire(self, *, cost=1):
        wait_total = 0.0
        wait_events = 0

        while True:
            now_ms = int(time.time() * 1000)
            try:
                allowed, wait_seconds = self._script(
                    keys=[self.key],
                    args=[now_ms, self.max_rps, float(cost)],
                )
            except Exception as exc:
                raise RateLimiterUnavailable("rate limiter unavailable") from exc

            allowed = int(allowed)
            wait_seconds = max(0.0, float(wait_seconds))

            if allowed == 1:
                return AcquireResult(wait_seconds=wait_total, wait_events=wait_events)

            wait_events += 1
            wait_total += wait_seconds
            if wait_seconds > 0:
                time.sleep(wait_seconds)


def build_rate_limiter():
    max_rps = settings.BANK_MAX_RPS
    if max_rps <= 0:
        return NoopRateLimiter()

    redis_url = settings.BANK_RATE_LIMIT_REDIS_URL
    try:
        import redis
    except Exception:
        logger.warning(
            "event=rate_limiter_disabled reason=redis_client_missing worker_role=sender"
        )
        return NoopRateLimiter()

    try:
        redis_client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=settings.BANK_REDIS_SOCKET_CONNECT_TIMEOUT,
            socket_timeout=settings.BANK_REDIS_SOCKET_TIMEOUT,
            decode_responses=True,
        )
        redis_client.ping()
    except Exception:
        logger.warning(
            "event=rate_limiter_disabled reason=redis_unavailable redis_url=%s worker_role=sender",
            redis_url,
        )
        return NoopRateLimiter()

    return RedisTokenBucketRateLimiter(
        redis_client=redis_client,
        key=settings.BANK_RATE_LIMIT_KEY,
        max_rps=max_rps,
    )
