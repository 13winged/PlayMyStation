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
    provider: str = "unknown"  # spotify | yandex | soundcloud


class BaseMusicService(ABC):
    """Базовый класс стратегии. Каждый сервис обязан вернуть текущий трек или None."""

    provider: str = "base"

    @abstractmethod
    async def get_currently_playing(self) -> TrackDTO | None:
        raise NotImplementedError
