from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = Field(min_length=8)
    database_url: str
    rabbitmq_url: str

    webhook_allowed_hosts: str = ""
    webhook_ssrf_relaxed: bool = False
    webhook_allow_http: bool = False

    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30

    rabbitmq_prefetch: int = 10
    outbox_batch_size: int = 20
    outbox_poll_interval_sec: float = 1.0
    outbox_claim_sec: int = 30
    outbox_publish_timeout_sec: float = 5.0

    gateway_sleep_min_sec: float = 2.0
    gateway_sleep_max_sec: float = 5.0
    gateway_sleep_ms: int | None = None

    webhook_timeout_sec: float = 10.0
    webhook_max_response_bytes: int = 65536

    enable_openapi: bool = False

    @field_validator("webhook_allowed_hosts", mode="before")
    @classmethod
    def _strip_hosts(cls, v: str | list[str]) -> str:
        if isinstance(v, list):
            return ",".join(v)
        return v or ""

    def allowed_webhook_hosts(self) -> frozenset[str]:
        parts = [h.strip().lower() for h in self.webhook_allowed_hosts.split(",") if h.strip()]
        return frozenset(parts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
