"""Единая конфигурация через pydantic-settings. Все секреты — только из .env."""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")

    database_url: str = Field(
        default="postgresql+asyncpg://playmystation:playmystation@localhost:5432/playmystation",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    fernet_key: str = Field(default="CHANGE_ME", alias="FERNET_KEY")

    spotify_client_id: str = Field(default="", alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: str = Field(default="", alias="SPOTIFY_CLIENT_SECRET")
    spotify_redirect_uri: str = Field(
        default="http://localhost:8000/oauth/spotify/callback", alias="SPOTIFY_REDIRECT_URI"
    )

    soundcloud_client_id: str = Field(default="", alias="SOUNDCLOUD_CLIENT_ID")
    soundcloud_client_secret: str = Field(default="", alias="SOUNDCLOUD_CLIENT_SECRET")
    soundcloud_redirect_uri: str = Field(
        default="http://localhost:8000/oauth/soundcloud/callback",
        alias="SOUNDCLOUD_REDIRECT_URI",
    )

    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
