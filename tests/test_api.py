import pytest
import asyncio
from httpx import AsyncClient

from app.config import Tier, load_env, settings
from app.redis_client import redis_client


# 1. Health Check Tests
@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health endpoint returns ok"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["redis"] == "connected"


@pytest.mark.asyncio
async def test_health_returns_rate_limit_header(client: AsyncClient):
    """Test /health returns X-RateLimit-Remaining header for portfolio demo."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert "x-ratelimit-remaining" in response.headers
    remaining = int(response.headers["x-ratelimit-remaining"])
    assert remaining >= 0


@pytest.mark.asyncio
async def test_check_returns_rate_limit_headers(client: AsyncClient):
    """Test /check returns X-RateLimit-* headers."""
    response = await client.post("/check", json={
        "identifier": "user:header_test",
        "tier": "free"
    })
    assert response.status_code == 200
    assert "x-ratelimit-remaining" in response.headers
    assert "x-ratelimit-limit" in response.headers
    assert int(response.headers["x-ratelimit-limit"]) == 100


# 2. Valid Request Tests
@pytest.mark.asyncio
async def test_rate_limit_allowed(client: AsyncClient):
    """Test normal request is allowed"""
    response = await client.post("/check", json={
        "identifier": "user:test1",
        "tier": "free"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] == True
    assert data["tokens_remaining"] == 99
    assert data["limit"] == 100


@pytest.mark.asyncio
async def test_tokens_decrement(client: AsyncClient):
    """Test tokens decrement with each request"""
    for i in range(3):
        response = await client.post("/check", json={
            "identifier": "user:test2",
            "tier": "free"
        })
    data = response.json()
    assert data["tokens_remaining"] == 97


@pytest.mark.asyncio
async def test_default_tier(client: AsyncClient):
    """Test default tier used when none specified"""
    response = await client.post("/check", json={
        "identifier": "user:test3"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 100  # free tier limit


# 3. Invalid Tier Test
@pytest.mark.asyncio
async def test_invalid_tier(client: AsyncClient):
    """Test 400 returned for invalid tier"""
    response = await client.post("/check", json={
        "identifier": "user:test4",
        "tier": "invalid_tier"
    })
    assert response.status_code == 400


# 4. Rate Limit Exhaustion Test
@pytest.mark.asyncio
async def test_rate_limit_exceeded(client: AsyncClient, monkeypatch):
    """Test 429 returned when limit exceeded"""
    monkeypatch.setitem(settings.rate_limit_config.tiers, "free", Tier(limit=100, window=600))
    # Exhaust free tier (100 requests)
    for i in range(100):
        await client.post("/check", json={
            "identifier": "user:test5",
            "tier": "free"
        })
    
    # 101st request should be rejected
    response = await client.post("/check", json={
        "identifier": "user:test5",
        "tier": "free"
    })
    assert response.status_code == 429
    data = response.json()
    assert "retry_after" in data["detail"]


# 5. Different Identifiers Test
@pytest.mark.asyncio
async def test_different_identifiers_independent(client: AsyncClient):
    """Test different users have independent limits"""
    # Exhaust user A
    for i in range(100):
        await client.post("/check", json={
            "identifier": "user:A",
            "tier": "free"
        })
    
    # User B should still be allowed
    response = await client.post("/check", json={
        "identifier": "user:B",
        "tier": "free"
    })
    assert response.status_code == 200


# 6. Different Tiers Test
@pytest.mark.asyncio
async def test_pro_tier_higher_limit(client: AsyncClient):
    """Test pro tier has higher limit than free"""
    response = await client.post("/check", json={
        "identifier": "user:pro1",
        "tier": "pro"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 1000


@pytest.mark.asyncio
async def test_concurrent_requests_are_atomic(client: AsyncClient, monkeypatch):
    monkeypatch.setitem(settings.rate_limit_config.tiers, "free", Tier(limit=20, window=600))
    responses = await asyncio.gather(*(
        client.post("/check", json={"identifier": "user:concurrent", "tier": "free"})
        for _ in range(100)
    ))
    statuses = [response.status_code for response in responses]
    assert statuses.count(200) == 20
    assert statuses.count(429) == 80
    assert all(status < 500 for status in statuses)


@pytest.mark.asyncio
async def test_retry_after_header_matches_body(client: AsyncClient, monkeypatch):
    monkeypatch.setitem(settings.rate_limit_config.tiers, "free", Tier(limit=20, window=600))
    for _ in range(20):
        await client.post("/check", json={"identifier": "user:retry-after", "tier": "free"})

    response = await client.post(
        "/check", json={"identifier": "user:retry-after", "tier": "free"}
    )
    assert response.status_code == 429
    retry_after = int(response.headers["retry-after"])
    assert 1 <= retry_after <= 30
    assert response.json()["detail"]["retry_after"] == retry_after


@pytest.mark.asyncio
async def test_refill_over_time(client: AsyncClient, monkeypatch):
    class FakeTime:
        current = 100.0

        @classmethod
        def time(cls):
            return cls.current

    monkeypatch.setitem(settings.rate_limit_config.tiers, "free", Tier(limit=2, window=10))
    monkeypatch.setattr("app.rate_limiter.time", FakeTime)

    for _ in range(2):
        response = await client.post("/check", json={"identifier": "user:refill", "tier": "free"})
        assert response.status_code == 200

    FakeTime.current = 105.0
    response = await client.post("/check", json={"identifier": "user:refill", "tier": "free"})
    assert response.status_code == 200
    response = await client.post("/check", json={"identifier": "user:refill", "tier": "free"})
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_tier_buckets_are_isolated(client: AsyncClient):
    identifier = "user:tier-isolation"
    free_response = await client.post("/check", json={"identifier": identifier, "tier": "free"})
    pro_response = await client.post("/check", json={"identifier": identifier, "tier": "pro"})
    assert free_response.status_code == 200
    assert pro_response.status_code == 200
    assert pro_response.json()["limit"] == 1000
    assert pro_response.json()["tokens_remaining"] == 999


@pytest.mark.asyncio
async def test_health_returns_503_when_redis_is_unreachable(client: AsyncClient, monkeypatch):
    async def unavailable():
        return False

    monkeypatch.setattr(redis_client, "ping", unavailable)
    response = await client.get("/health")
    assert response.status_code == 503


def test_env_defaults(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    env = load_env()
    assert env.redis_url == "redis://localhost:6379"
    assert env.log_level == "INFO"


@pytest.mark.asyncio
async def test_contention_exhausted_returns_503(client: AsyncClient, monkeypatch):
    monkeypatch.setattr("app.rate_limiter.MAX_ATTEMPTS", 0)
    response = await client.post("/check", json={"identifier": "user:busy", "tier": "free"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
