"""Паттерн 'Стратегия': единый контракт для всех музыкальных провайдеров."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class TrackDTO:
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None
    progress_ms: int | None = None
    is_playing: bool = False
    cover_url: str | None = None
    track_url: str | None = None
    provider: str = "unknown"  # spotify | yandex | youtube | lastfm
    # Прямая ссылка на воспроизводимое аудио, если сервис её отдаёт:
    # Spotify — 30-секундное preview_url. У Яндекса/YouTube/Last.fm — всегда None.
    preview_url: str | None = None
    # Нативный ID трека в сервисе (YouTube videoId, Яндекс track id).
    # Нужен для докачки полного аудио через download_track().
    track_id: str | None = None


class BaseMusicService(ABC):
    """Базовый класс стратегии. Каждый сервис обязан вернуть текущий трек или None."""

    provider: str = "base"
    # Флаги возможностей (эволюция под управление воспроизведением):
    # управление показывают кнопками только сервисы с supports_control/like.
    supports_control: bool = False  # play/pause/next/previous
    supports_like: bool = False  # добавить текущий трек в любимое

    @abstractmethod
    async def get_currently_playing(self) -> TrackDTO | None:
        raise NotImplementedError

    async def download_track(
        self, track: TrackDTO, youtube_auth: str | None = None
    ) -> tuple[bytes, str] | None:
        """Скачать полное аудио трека. Возвращает (байты, расширение) или None.

        Дефолт — не поддерживается (Last.fm). Переопределяют сервисы,
        у которых есть доступ к аудио: Яндекс (прямые ссылки),
        YouTube (поток/yt-dlp), Spotify (матчинг + 30-сек preview_url).
        youtube_auth — auth-JSON YouTube-привязки юзера: матчинг Spotify/Last.fm
        качает через него (OAuth-поток или куки), иначе бан серверного IP.
        """
        return None

    async def set_playing(self, playing: bool) -> str:
        """Продолжить (True) или поставить на паузу (False).

        Возвращает: ok | premium | no_device | unsupported | error.
        """
        return "unsupported"

    async def skip(self, direction: str = "next") -> str:
        """Следующий (next) или предыдущий (previous) трек. Тот же статус."""
        return "unsupported"

    async def like_track(self, track: TrackDTO) -> str:
        """Добавить трек в любимое. Тот же статус."""
        return "unsupported"
