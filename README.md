# 🎵 PlayMyStation

Асинхронный мультиаккаунтный Telegram-бот: **Spotify + Яндекс Музыка + SoundCloud** в одном `/now`.

## Стек
Python 3.11+ · aiogram 3.x · FastAPI (OAuth callbacks) · SQLAlchemy 2.0 Async + PostgreSQL ·
Redis · httpx · yandex-music · Docker Compose

## Быстрый старт
```bash
cp .env.example .env        # заполнить BOT_TOKEN, FERNET_KEY, OAuth-клиенты
docker compose up --build
# бот: polling Telegram; web: http://localhost:8000/health
# OAuth: /oauth/spotify/callback, /oauth/soundcloud/callback
```

Локально без Docker:
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e .[dev]
python -m app.main
```

## Архитектура
- `app/db/models.py` — `users` (telegram_id, active_provider) + `integrations` (UniqueConstraint user+provider)
- `app/services/base.py` — `TrackDTO` + `BaseMusicService.get_currently_playing()`
- `app/services/spotify.py | yandex.py | soundcloud.py` — 3 стратегии
- `app/services/factory.py` — `build_service()` + `resolve_now_playing()` (режим `all` опрашивает всё параллельно)
- `app/bot/` — хэндлеры `/start /services /now /np /yandex`, клавиатуры, `track_card()` с прогресс-баром
- `app/web/oauth.py` — OAuth2 callbacks (state=telegram_id), обмен code→token, upsert в БД
- `app/main.py` — polling + uvicorn в одном asyncio-процессе

## Мультиаккаунтинг
У пользователя **по одному аккаунту каждого провайдера**. `active_provider ∈ {spotify, yandex, soundcloud, all}`.
`/now`: если `all` — `asyncio.gather` по всем привязанным, приоритет треку с `is_playing=True`.

## Ограничения API (честно)
- **Spotify** — полноценный realtime (`currently-playing` + авторефреш токена).
- **Яндекс** — нет `currently playing` в API → читаем очередь (`queues_list`), прогресс недоступен.
- **SoundCloud** — нет realtime → `play-history` / фолбэк `favorites`, помечаем как «последний трек».

## Карта разработки
См. [ROADMAP.md](./ROADMAP.md).
