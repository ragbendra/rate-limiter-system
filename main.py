from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from app.redis_client import redis_client
from app.rate_limiter import RateLimiterBusy, rate_limiter
from app.config import settings
from redis.exceptions import RedisError
import logging
from typing import Optional

logging.basicConfig(level=settings.env.log_level.upper())
logger = logging.getLogger(__name__)

class RateLimitRequest(BaseModel):
    identifier: str
    tier: Optional[str] = None


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://raghabendra.dev",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-RateLimit-Remaining", "X-RateLimit-Limit", "X-RateLimit-Reset"],
)


@app.get("/health")
async def health_check():
    try:
        pong = await redis_client.ping()
        body = {
            "status": "ok",
            "redis": "connected" if pong else "unreachable",
        }
        if not pong:
            raise HTTPException(status_code=503, detail="Redis unavailable")

        # Run a demo rate-limit check so we can surface X-RateLimit-* headers
        # for the portfolio "Try It" button.
        headers = {}
        try:
            demo_result = await rate_limiter.check_rate_limit(
                identifier="demo:health",
                tier=settings.rate_limit_config.default_tier,
            )
            headers["X-RateLimit-Remaining"] = str(demo_result["tokens_remaining"])
            headers["X-RateLimit-Limit"] = str(demo_result["limit"])
            headers["X-RateLimit-Reset"] = str(int(demo_result["reset_at"]))
        except Exception:
            logger.debug("Demo rate-limit check skipped")

        return JSONResponse(content=body, headers=headers)
    except Exception as e:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Service Unavailable")


@app.post("/check", response_model=RateLimitResponse)
async def rate_limit(request: RateLimitRequest):
    tier = request.tier or settings.rate_limit_config.default_tier

    if tier not in settings.rate_limit_config.tiers:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")

    try:
        result = await rate_limiter.check_rate_limit(
            identifier=request.identifier,
            tier=tier
        )
    except RateLimiterBusy:
        return JSONResponse(
            status_code=503,
            content={"detail": "Rate limiter busy"},
            headers={"Retry-After": "1"},
        )
    except (RedisError, ConnectionError):
        return JSONResponse(
            status_code=503,
            content={"detail": "Redis unavailable"},
            headers={"Retry-After": "1"},
        )

    rate_headers = {
        "X-RateLimit-Remaining": str(result["tokens_remaining"]),
        "X-RateLimit-Limit": str(result["limit"]),
        "X-RateLimit-Reset": str(int(result["reset_at"])),
    }

    # Return 429 if rate limited
    if not result["allowed"]:
        rate_headers["Retry-After"] = str(result["retry_after"])
        return JSONResponse(
            status_code=429,
            content={
                "detail": {
                    "allowed": False,
                    "retry_after": result.get("retry_after"),
                    "reset_at": result["reset_at"],
                    "limit": result["limit"],
                }
            },
            headers=rate_headers,
        )

    return JSONResponse(
        content=RateLimitResponse(
            allowed=result["allowed"],
            tokens_remaining=result["tokens_remaining"],
            reset_at=result["reset_at"],
            limit=result["limit"],
        ).model_dump(),
        headers=rate_headers,
    )
