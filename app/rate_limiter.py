import time
import json
import logging
from app.config import settings
from app.redis_client import redis_client


logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self):
        self.redis = redis_client
        self.config = settings
    
    # 5
    async def check_rate_limit(self, identifier: str, tier: str = None) -> dict:
        if tier is None:
            tier = self.config.rate_limit_config.default_tier
        # get tier config
        tier_config = self.config.get_tier(tier)
        limit = tier_config.limit
        window = tier_config.window
        # calculate refill rate
        refill_rate = limit / window
        # get redis key
        key = self._get_redis_key(identifier)
        # get bucket state
        state = await self._get_bucket_state(key, limit)

        # calculate new tokens
        new_tokens, current_time = self._calculate_tokens(
            current_tokens=state["tokens"],
            last_refill=state["last_refill"],
            refill_rate=refill_rate,
            capacity=limit
        )

        # check if allowed
        if new_tokens >= 1:
            # consume tokens
            new_tokens -= 1

            # save state
            await self._save_bucket_state(
                key=key,
                state={"tokens": new_tokens, "last_refill":current_time}, ttl=window*2
            )

            return {
                "allowed": True,
                "tokens_remaining": int(new_tokens),
                "reset_at": current_time + window,
                "limit" : limit
            }
        else:
            # denied, dont save state
            return {
                "allowed": False,
                "tokens_remaining": 0,
                "reset_at": current_time + window,
                "limit" : limit,
                "retry_after": window
            }


    # 2
    def _get_redis_key(self, identifier: str) -> str:
        return f"rate_limit:{identifier}"

    # 3
    async def _get_bucket_state(self, key: str, capacity: int) -> dict:
        # get data from redis
        client = self.redis.get_client()

        data = await client.get(key)
        # if None(first request), then return full bucket
        if data is None:
            return {
                "tokens": float(capacity),
                "last_refill" : time.time()
            }
        
        return json.loads(data)

    # 4
    async def _save_bucket_state(self, key: str, state: dict, ttl: int):
        client = self.redis.get_client()

        await client.set(key, json.dumps(state), ex=ttl)

    # 1
    def _calculate_tokens(self, current_tokens: float, last_refill: float, refill_rate: float, capacity: int) -> tuple:
        current_time = time.time()
        elapsed_time = current_time - last_refill

        if elapsed_time < 0:
            logger.warning(f"Negative elapsed time detected: {elapsed_time}s resetting to 0.")
            elapsed_time = 0
        
        added_tokens = elapsed_time * refill_rate
        new_tokens = min(capacity, current_tokens + added_tokens)

        return new_tokens, current_time



# Singleton
rate_limiter = RateLimiter()

if __name__ == "__main__":
    print(__name__)
        