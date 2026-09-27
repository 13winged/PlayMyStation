<div align="center">

# 🎵 PlayMyStation @playmystation_bot

**One `/now` for all your music — Spotify, Yandex Music, YouTube Music and Last.fm in a single Telegram bot.**

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-8B2BE6?style=flat-square)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](./pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)](./docker-compose.yml)
[![CI](https://github.com/13winged/PlayMyStation/actions/workflows/ci.yml/badge.svg)](https://github.com/13winged/PlayMyStation/actions)
[![Ruff](https://img.shields.io/badge/ruff-checked-ef3939?style=flat-square)](./pyproject.toml)

> 🇷🇺 Русская версия: [README_RU.md](./README_RU.md)

</div>

---

## Demo

```
/now
```

```
▶️ YouTube Music — ⏸️ Last track
Pretty Boy (feat. Lil Yachty)
Joji
2:38
🔗 Open track
[ ▶️ YouTube Music ] [ 🔴 Yandex Music ] [ 🟢 Spotify ]
[ ⏬ Preview (30 sec) ]
[ ⚙️ My services ]
🎵 <audio file follows>
```

Card in the Spotify-player style, platform buttons, and the audio itself —
all automatic, in background, best-effort.

---

## Features

| Area | What |
|---|---|
| **`/now` (`/np`)** | Polls the active service — or all at once (ALL mode, priority to the actually-playing track) |
| **Audio** | Full track follows the card: Yandex direct links, YouTube via `yt-dlp`, Spotify/Last.fm via YouTube matching; `file_id` cache = instant repeats |
| **Controls** | ⏸/▶️/⏭/⏮/❤️ under Spotify cards (Premium + active device required) |
| **Links** | Track URL pasted in chat or group → card + audio (one job per user) |
| **Cross-links** | "Same track on …" buttons via native search matching (duration-checked) |
| **Accounts** | Up to 4 bindings, active-service switch, `/disconnect` |
| **Languages** | RU/EN via `/lang` |
| **Ops** | Prometheus `/metrics`, `/health` + `/ready`, Sentry, JSON logs, Postgres backups, audit log |

---

## Providers (honest)

| Provider | Now playing | Audio | Binding |
|---|---|---|---|
| 🟢 **Spotify** | realtime API — needs Premium on the **app-owner** account, otherwise 403 for everyone | full track via YouTube matching (±7s duration check), 30-sec preview fallback | OAuth |
| 🔴 **Yandex Music** | realtime (Ynison native protocol) / queue fallback | full track (mp3/aac links) | token |
| ▶️ **YouTube Music** | history (`get_history`) | full track (m4a) | OAuth device-flow (link + code, no DevTools) or browser headers |
| 🟪 **Last.fm** | scrobble (`nowplaying` flag) — the way out for Spotify Free | via YouTube matching | username (no OAuth) |

---

## Commands

| Command | What |
|---|---|
| `/start` | Onboarding + services |
| `/services` | Connect / pick active service |
| `/now`, `/np` | What's playing (+ audio) |
| `/spotify`, `/yandex`, `/youtube`, `/lastfm` | Select mode — or connect if unbound |
| `/lang` | RU/EN |
| `/disconnect <provider>` | Unlink |
| *track link in chat* | Download + send (groups: link, `@mention` + link, or reply with link) |

---

## Quick start

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

Tests: `python -m pytest -q` (200) · Linter: `ruff check app tests`

---

## Architecture

| Layer | Files |
|---|---|
| Provider strategies | `app/services/spotify\|yandex\|youtube\|lastfm.py` — `BaseMusicService` + `TrackDTO`, factory with ALL mode, bulkhead timeouts, circuit breakers |
| Yandex realtime | `app/services/ynison/` + `ynison-proxy/` — native-protocol gRPC + Go sidecar |
| Bot | `app/bot/` — handlers, keyboards, `track_card()`, RU/EN (`i18n.py`), delivery (`delivery.py`) |
| Web | `app/web/` — Spotify OAuth callback (CSRF state), `/health`, `/ready`, `/metrics`, Telegram webhook (secret required) |
| Core | `app/core/` — config, DB, Redis, retry, metrics, Sentry/structlog, Fernet encryption (+ rotation), audit log |

---

## Self-hosting

Full guide — server, OAuth apps, deploy, backups, monitoring, troubleshooting:
**[README_FOR_YOUR_SERVER.md](./README_FOR_YOUR_SERVER.md)**

---

## FAQ

**`/now` is silent on Spotify, logs say `403 … owner of the app`?**
Realtime needs Premium on the Spotify **app owner's** account — for every user,
even Premium ones. Unlock takes up to a few hours after subscribing.

**YouTube returns empty history while music plays?**
The binding looks at the wrong profile: paused history (`myactivity.google.com`),
another Google account, or a brand account. Rebind (`/youtube`) from the right profile.

**Downloads fail with `cookies are no longer valid`?**
Google rotates cookies — rebind with fresh headers, or better finish OAuth
(test users in Google Cloud Console). The bot tells you this itself now.

**`Sign in to confirm you're not a bot`?**
Covered: user cookies + tv/web clients + EJS solver with Node 22 in the image.
If it persists — your datacenter IP is hardlisted, proxy `yt-dlp` traffic.

**Only MP3, no FLAC from Yandex?**
By design: most FLACs don't fit Telegram limits; MP3 320 is picked automatically,
preview variants are skipped.

---

## Roadmap

- [ROADMAP.md](./ROADMAP.md) — Telegram bot
- [ROADMAP_DISCORD.md](./ROADMAP_DISCORD.md) — Discord mirror plan

---

## Contributing

Issues and PRs welcome. Stack: Python 3.11+, aiogram, FastAPI, PostgreSQL, Redis.
`ruff` + `pytest` must stay green. Docs live in `README_RU.md` too — keep them in sync.

---

## License

[Apache-2.0](./LICENSE) — see [LICENSE](./LICENSE) for details.

Inspired by [es3n1n/nowplaying](https://github.com/es3n1n/nowplaying)
(`playinnowbot`, Apache-2.0): capability flags, Last.fm as a source, Ynison
realtime, audio cache. The Go proxy and protobuf modules are ported verbatim
(with attribution); everything else is original code.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=13winged/PlayMyStation&type=date)](https://www.star-history.com/?type=date&repos=13winged/PlayMyStation)
