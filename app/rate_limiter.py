import asyncio
import json
import logging
import math
import random
import time

from redis.exceptions import WatchError

from app.config import settings
from app.redis_client import redis_client

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 50


class RateLimiterBusy(Exception):
    """Raised when optimistic-lock retries are exhausted for a key."""


class RateLimiter:
    def __init__(self):
        self.redis = redis_client
        self.config = settings

    async def check_rate_limit(self, identifier: str, tier: str = None) -> dict:
        tier = tier or self.config.rate_limit_config.default_tier
        tier_config = self.config.get_tier(tier)
        limit, window = tier_config.limit, tier_config.window
        refill_rate = limit / window
        key = f"rate_limit:{tier}:{identifier}"
        client = self.redis.get_client()

        for _ in range(MAX_ATTEMPTS):
            async with client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    now = time.time()
                    if raw is None:
                        tokens, last = float(limit), now
                    else:
                        data = json.loads(raw)
                        tokens, last = data["tokens"], data["last_refill"]
                    tokens = min(limit, tokens + max(0.0, now - last) * refill_rate)

                    if tokens < 1:
                        retry_after = max(1, math.ceil((1 - tokens) / refill_rate))
                        return {
                            "allowed": False,
                            "tokens_remaining": 0,
                            "reset_at": now + retry_after,
                            "limit": limit,
                            "retry_after": retry_after,
                        }

                    tokens -= 1
                    pipe.multi()
                    pipe.set(
                        key,
                        json.dumps({"tokens": tokens, "last_refill": now}),
                        ex=window * 2,
                    )
                    await pipe.execute()
                    return {
                        "allowed": True,
                        "tokens_remaining": int(tokens),
                        "reset_at": now + window,
                        "limit": limit,
                    }
                except WatchError:
                    await asyncio.sleep(random.uniform(0, 0.005))
        raise RateLimiterBusy(key)


rate_limiter = RateLimiter()
