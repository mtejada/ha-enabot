"""Configuration — all values come from the environment (see .env.example)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    # --- this API ---
    api_title: str = "EBO SE 2 Control API"
    api_version: str = "1.0.0"
    # Comma-separated bearer keys that clients must present (Authorization: Bearer <key>).
    api_keys: str = Field(default="", description="comma-separated client API keys")
    # Fail-open only if explicitly allowed (dev). Otherwise the app refuses to start with no keys.
    allow_no_auth: bool = False
    cors_origins: str = "*"          # comma-separated, or * for any

    # --- the engine (internal control plane) ---
    engine_url: str = "http://ebo-engine:8098"
    engine_token: str = ""           # == the engine's EBO_API_TOKEN
    request_timeout: float = 15.0

    # --- video ---
    # Host clients should use to reach the engine's RTSP (the engine is internal to the compose net).
    rtsp_public_host: str = "localhost"
    rtsp_port: int = 8554

    # --- realtime ---
    events_poll_seconds: float = 2.0

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
