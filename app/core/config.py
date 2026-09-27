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
    # Старые ключи через запятую — только для чтения при ротации (см. README).
    fernet_keys_old: str = Field(default="", alias="FERNET_KEYS_OLD")

    spotify_client_id: str = Field(default="", alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: str = Field(default="", alias="SPOTIFY_CLIENT_SECRET")
    spotify_redirect_uri: str = Field(
        default="http://localhost:8000/oauth/spotify/callback", alias="SPOTIFY_REDIRECT_URI"
    )

    # Last.fm: только API-ключ сервера + username юзера (OAuth не нужен)
    lastfm_api_key: str = Field(default="", alias="LASTFM_API_KEY")

    # YouTube Music OAuth (device-flow): Google Cloud Console → YouTube Data API v3
    # включён → OAuth-клиент типа «TVs and Limited Input devices».
    ytm_oauth_client_id: str = Field(default="", alias="YTM_OAUTH_CLIENT_ID")
    ytm_oauth_client_secret: str = Field(default="", alias="YTM_OAUTH_CLIENT_SECRET")

    # Кеш аудио: ID приватного канала, куда бот (админ) складывает треки
    # для повторной отдачи по file_id. 0 — кеш канала выключен.
    audio_cache_channel_id: int = Field(default=0, alias="AUDIO_CACHE_CHANNEL_ID")

    # Наблюдаемость (Milestone 3): Sentry DSN + формат логов (text|json)
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")
    log_format: str = Field(default="text", alias="LOG_FORMAT")

    # Ynison-прокси (Go-сайдкар): транспорт для gRPC-стримов нативного
    # протокола Яндекс Музыки. В compose доступен как сервис `ynison`.
    ynison_proxy_host: str = Field(default="ynison", alias="YNISON_PROXY_HOST")
    ynison_proxy_port: int = Field(default=50051, alias="YNISON_PROXY_PORT")

    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")

    # Webhook settings (если заданы — используется webhook вместо polling)
    webhook_url: str = Field(default="", alias="WEBHOOK_URL")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    webhook_path: str = Field(default="/webhook", alias="WEBHOOK_PATH")

    @property
    def use_webhook(self) -> bool:
        """True если настроен webhook_url — переключаемся на webhook mode."""
        return bool(self.webhook_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
