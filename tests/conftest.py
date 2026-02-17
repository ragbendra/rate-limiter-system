import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app
from app.redis_client import redis_client


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create test client with Redis connected"""
    await redis_client.connect()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac
    await redis_client.close()


@pytest_asyncio.fixture(autouse=True)
async def flush_redis():
    """Clear Redis before each test"""
    await redis_client.connect()
    await redis_client.get_client().flushdb()
    yield
    await redis_client.close()