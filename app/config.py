from dotenv import load_dotenv
import os
import yaml
from pydantic import BaseModel, Field, model_validator
from typing import Dict
load_dotenv()

class EnvConfig(BaseModel):
    redis_url: str
    log_level: str = "INFO"
    fail_mode: str = "CLOSED"

def load_env() -> EnvConfig:
    return EnvConfig(
        redis_url= os.getenv("REDIS_URL"),
        log_level= os.getenv("LOG_LEVEL"),
        fail_mode= os.getenv("FAIL_MODE")
    )

class Tier(BaseModel):
    limit: int = Field(gt=0)
    window: int = Field(gt=0)

class RateLimitConfig(BaseModel):
    tiers: Dict[str, Tier]
    default_tier: str

    @model_validator(mode="after")
    def validate_tiers(self):
        if self.default_tier not in self.tiers:
            raise ValueError(f"Default tier '{self.default_tier}' is not defined in tiers")
        return self



def load_config() -> RateLimitConfig:
    with open("config.yaml", "r") as f:
        yaml_config = yaml.safe_load(f)
    return RateLimitConfig(**yaml_config)

class Settings:
    def __init__(self):
        self.env = load_env()
        self.rate_limit_config = load_config()
    
    def get_tier(self, tier_name: str) -> Tier:
        return self.rate_limit_config.tiers.get(
            tier_name,
            self.rate_limit_config.tiers[self.rate_limit_config.default_tier],
        )



settings = Settings()

