# 🎵 PlayMyStation

> 🇷🇺 Русская версия: [README_RU.md](./README_RU.md)

Async multi-account Telegram bot: **Spotify + Yandex Music + YouTube Music + Last.fm** in a single `/now` — track card, audio attached, playback controls.

## Features

- `/now` (`/np`) — what's playing: polls the active service or all at once (ALL mode, priority to the actually-playing track), Spotify-style card + audio follows
- Buttons under the card: ⏸/▶️/⏭/⏮/❤️ for Spotify, "same track on …" (cross-matching), "⏬ Preview", "My services"
- Track links from chat and groups (Spotify/Yandex/YouTube) → card + audio
- `/services` — connect up to 4 accounts, pick the active one; `/spotify /yandex /youtube /lastfm` switch mode if the service is bound
- `/lang` — RU/EN, `/disconnect` — unlink

## Stack

Python 3.11+ · aiogram 3.x · FastAPI · SQLAlchemy 2.0 Async + PostgreSQL · Redis ·
httpx · yandex-music · ytmusicapi · yt-dlp · Docker Compose

## Quick start (local)

```bash
cp .env.example .env        # fill in BOT_TOKEN, FERNET_KEY
docker compose up --build
# bot: polling (or webhook if WEBHOOK_URL is set); web: http://localhost:8000/health
# Alembic migrations apply automatically on startup
```

Without Docker:

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e .[dev]
python -m app.main
```

Tests: `python -m pytest -q` (200), linter: `ruff check app tests`.

## Providers (honest)

| Provider | Now playing | Audio | Binding |
|---|---|---|---|
| Spotify | realtime API (requires Premium on the app-owner account, otherwise 403) | full track via YouTube matching, 30-sec preview fallback | OAuth |
| Yandex Music | realtime (Ynison) / queue | full track | token |
| YouTube Music | history | full track | OAuth device-flow / headers |
| Last.fm | scrobble (`nowplaying`) | via YouTube matching | username |

## Architecture (brief)

- `app/services/` — provider strategies (`BaseMusicService` + `TrackDTO`), factory with ALL mode, bulkhead timeouts, circuit breakers
- `app/services/ynison/` + `ynison-proxy/` — Yandex Music realtime (gRPC + Go sidecar)
- `app/bot/` — handlers, keyboards, `track_card()`, RU/EN (`i18n.py`), audio delivery (`delivery.py`)
- `app/web/` — FastAPI: Spotify OAuth callback (CSRF state), `/health`, `/ready`, `/metrics`, Telegram webhook (secret required)
- `app/core/` — config, DB, Redis, retry, metrics, Sentry/structlog, token encryption (Fernet + rotation), audit log

## Docs

- [README_FOR_YOUR_SERVER.md](./README_FOR_YOUR_SERVER.md) — self-hosting (Russian): server, OAuth apps, deploy, backups, monitoring, troubleshooting
- [ROADMAP.md](./ROADMAP.md) — development map (Russian)
- [ROADMAP_DISCORD.md](./ROADMAP_DISCORD.md) — Discord mirror plan (Russian)
- [`.env.example`](./.env.example) — all variables with comments
- [LICENSE](./LICENSE) — Apache-2.0

## Inspired by

Architecture reference — [es3n1n/nowplaying](https://github.com/es3n1n/nowplaying)
(`playinnowbot`, Apache-2.0): capability-flag ideas, Last.fm as a source,
Ynison realtime and audio cache. The Go proxy `ynison-proxy/` and protobuf
modules are ported verbatim (Apache-2.0, with attribution); the rest is
original code.
