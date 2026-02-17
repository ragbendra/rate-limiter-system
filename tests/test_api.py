import pytest
from httpx import AsyncClient


# 1. Health Check Tests
@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health endpoint returns ok"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["redis"] == "connected"


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
async def test_rate_limit_exceeded(client: AsyncClient):
    """Test 429 returned when limit exceeded"""
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
