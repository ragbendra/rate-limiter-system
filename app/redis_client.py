import redis.asyncio as redis
import asyncio
import logging
from app.config import settings

logger = logging.getLogger(__name__)

class RedisClient:
    def __init__(self):
        self.redis_url = settings.env.redis_url
        self.client = None
        self.is_connected = False

    def get_client(self) -> redis.Redis:
        if not self.is_connected or self.client is None:
            raise Exception("Redis client is not connected.")
        return self.client

    async def connect(self):
        max_retries = 3
        retry_delay = 2 # seconds
        for attempt in range(max_retries):
            try:
                self.client = redis.from_url(self.redis_url) # create redis client
                await self.client.ping()  # force connection to redis
                self.is_connected = True # set connection status or commit
                logger.info("Connected to Redis successfully.")
                return
            except Exception as e:
                logger.warning(f"Redis attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error("Failed to connect after several retries.")
                    raise

    async def ping(self):
        if not self.client:
            return False
        try:
            await self.client.ping()
            return True
        except Exception:
            return False

    async def close(self):
        if self.client:
            await self.client.close()
            self.is_connected = False
            self.client = None

redis_client = RedisClient()