from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from app.redis_client import redis_client
from app.rate_limiter import rate_limiter
from app.config import settings
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class RateLimitRequest(BaseModel):
    identifier: str
    tier: str = None


class RateLimitResponse(BaseModel):
    allowed: bool
    tokens_remaining: int
    reset_at: float
    limit: int
    retry_after: Optional[int] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting rate limiter system...")

    try:
        await redis_client.connect()
        logger.info("Redis connected")
        yield
    finally:
        await redis_client.close()
        logger.info("Redis closed")


app = FastAPI(
    title="Rate Limiter System",
    description="Token Bucket Rate Limiter System",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/health")
async def health_check():
    try:
        pong = await redis_client.ping()
        return {
            "status" : "ok",
            "redis" : "connected" if pong else "unreachable"
        }
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Service Unavailable")


@app.post("/check", response_model=RateLimitResponse)
async def rate_limit(request: RateLimitRequest):
    tier = request.tier or settings.rate_limit_config.default_tier

    if tier not in settings.rate_limit_config.tiers:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")

    result = await rate_limiter.check_rate_limit(
        identifier=request.identifier,
        tier=tier
    )

    # Return 429 if rate limited
    if not result["allowed"]:
        raise HTTPException(
            status_code=429,
            detail={
                "allowed": False,
                "retry_after": result.get("retry_after"),
                "reset_at": result["reset_at"],
                "limit": result["limit"]
            }
        )

    return RateLimitResponse(
        allowed=result["allowed"],
        tokens_remaining=result["tokens_remaining"],
        reset_at=result["reset_at"],
        limit=result["limit"]
    )


# if __name__ == "__main__":
#     asyncio.run(main())