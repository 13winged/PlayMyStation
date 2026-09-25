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

## CI/CD & Deploy

- **CI** (`.github/workflows/ci.yml`): ruff + compileall + pytest + docker build — на каждый push/PR.
- **CD** (`.github/workflows/deploy.yml`): пуш в `master` → SSH на прод-сервер → `git pull` → `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` → healthcheck. Прод-override добавляет `restart: unless-stopped` и **Caddy** (авто-https через Let's Encrypt).

Подготовка сервера (Ubuntu, один раз, по SSH):
```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER   # затем перелогиниться
sudo ufw allow 22,80,443/tcp && sudo ufw enable
```

SSH-ключ для деплоя (на своей машине):
```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\playmystation_deploy -N '""'
```
Публичный ключ добавить на сервер в `~/.ssh/authorized_keys`, приватный — в секрет `SSH_PRIVATE_KEY`.

GitHub Secrets (репозиторий → Settings → Secrets and variables → Actions):
| Секрет | Значение |
|---|---|
| `SSH_HOST` | IP сервера, напр. `45.86.66.95` |
| `SSH_PORT` | `22` |
| `SSH_USER` | пользователь на сервере |
| `SSH_PRIVATE_KEY` | приватный ключ деплоя целиком |
| `GH_PAT` | fine-grained PAT с `contents:read` на этот репозиторий (нужен для `git clone/pull` приватного репо) |
| `DOMAIN` | домен, напр. `music.example.com` (A-запись → IP сервера) |
| `ENV_PROD` | содержимое прод-`.env` целиком (см. ниже) |

`ENV_PROD` (шаблон):
```
BOT_TOKEN=...
FERNET_KEY=...
DATABASE_URL=postgresql+asyncpg://playmystation:playmystation@postgres:5432/playmystation
REDIS_URL=redis://redis:6379/0
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=https://<DOMAIN>/oauth/spotify/callback
PUBLIC_BASE_URL=https://<DOMAIN>
WEB_HOST=0.0.0.0
WEB_PORT=8000
```

⚠️ **Важно про Spotify**: Redirect URI, отличные от `localhost`, обязаны быть `https` — иначе Spotify их отклонит. Поэтому прод требует **домен + Caddy** (уже в compose). После деплоя добавь `https://<DOMAIN>/oauth/spotify/callback` в Spotify Dashboard → Settings → Redirect URIs.

## Карта разработки
См. [ROADMAP.md](./ROADMAP.md).
