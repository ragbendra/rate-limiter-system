from app.config import settings
from app.redis_client import redis_client
import asyncio
import logging


logging.basicConfig(level=logging.INFO)

async def main():
    await redis_client.connect()
    
    tier = settings.get_tier("free")

    print("Redis:", settings.env.redis_url)
    print("Limit:", tier.limit)
    print("Window:", tier.window)

    await redis_client.close()


if __name__ == "__main__":
    asyncio.run(main())
