# 🎵 PlayMyStation

Асинхронный мультиаккаунтный Telegram-бот: **Spotify + Яндекс Музыка + YouTube Music + Last.fm** в одном `/now`.

## Стек
Python 3.11+ · aiogram 3.x · FastAPI (OAuth callbacks) · SQLAlchemy 2.0 Async + PostgreSQL ·
Redis · httpx · yandex-music · Docker Compose

## Быстрый старт
```bash
cp .env.example .env        # заполнить BOT_TOKEN, FERNET_KEY, OAuth-клиенты
docker compose up --build
# бот: polling Telegram (или webhook, если задан WEBHOOK_URL); web: http://localhost:8000/health
# OAuth: /oauth/spotify/callback
# Миграции Alembic применяются автоматически при старте приложения
```

Локально без Docker:
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e .[dev]
python -m app.main
```

## Архитектура
- `app/db/models.py` — `users` (telegram_id, active_provider) + `integrations` (UniqueConstraint user+provider)
- `alembic/versions/` — миграции БД (применяются при старте, вместо `create_all`)
- `app/services/base.py` — `TrackDTO` (+`preview_url`) + `BaseMusicService.get_currently_playing()`
- `app/services/spotify.py | yandex.py | youtube.py | lastfm.py` — 4 стратегии + `audio.py` (скачивание превью с лимитом)
- `app/services/ynison/` — gRPC-клиент нативного протокола Яндекс Музыки + Go-сайдкар `ynison-proxy/` (realtime: трек + прогресс + пауза)
- `app/services/factory.py` — `build_service()` + `resolve_now_playing()` (режим `all` опрашивает всё параллельно, приоритет `is_playing=True`); результат кешируется в Redis на ~20 сек
- `app/core/retry.py` — ретраи httpx (exponential backoff, `Retry-After`) + circuit-breaker для внешних API
- `app/bot/` — хэндлеры `/start /services /now /np /yandex /spotify /youtube /lastfm /disconnect`, клавиатуры, `track_card()` с прогресс-баром (весь динамический текст экранируется под Telegram HTML); кнопка «⏬ Превью» под карточкой
- `app/web/oauth.py` — OAuth2 callback Spotify (state=telegram_id), обмен code→token, upsert в БД
- `app/web/app.py` — FastAPI: `/health`, OAuth callbacks, `POST /webhook` (проверка `X-Telegram-Bot-Api-Secret-Token`)
- `app/main.py` — dual-режим: **polling** (по умолчанию) или **webhook** (если задан `WEBHOOK_URL`); graceful shutdown, `delete_webhook` при старте polling-режима

## Мультиаккаунтинг
У пользователя **по одному аккаунту каждого провайдера**. `active_provider ∈ {spotify, yandex, youtube, lastfm, all}`.
`/now`: если `all` — `asyncio.gather` по всем привязанным, приоритет треку с `is_playing=True`.

## Ограничения API (честно)
- **Spotify** — полноценный realtime (`currently-playing` + авторефреш токена), но:
  - приложение в Development Mode требует **Premium на аккаунте-владельце приложения** (иначе все user-запросы → `403`, см. [quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes));
  - free-аккаунты получают `403` на realtime player API — бот падает назад на `recently-played` («последний трек»);
  - больше 5 пользователей — только через allowlist (User Management) или Extended Quota (только для организаций).
- **Яндекс** — realtime через **Ynison** (нативный протокол: трек + прогресс + пауза, проверено на проде); фолбэк — очередь (`queues_list`, без прогресса). Привязка: `/yandex <токен>` (токен через официальный OAuth implicit flow, relay мёртв).
- **YouTube Music** — нет realtime → история `get_history` через ytmusicapi (browser auth), помечаем как «последний трек». Привязка: `/youtube <полные заголовки>` (Copy Request Headers из DevTools на music.youtube.com, живут ~2 года).
- **Last.fm** — `user.getrecenttracks` по username (OAuth не нужен, Premium не нужен); трек с флагом `nowplaying` считаем играющим, иначе «последний трек». Выход для free-юзеров Spotify через скробблинг.

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
| `SSH_PRIVATE_KEY` | приватный ключ деплоя целиком (без passphrase) |
| `DOMAIN` | домен, напр. `music.example.com` (A-запись → IP сервера) |
| `ENV_PROD` | содержимое прод-`.env` целиком (см. ниже) |

Деплой ходит в Git по SSH, поэтому на сервере нужен доступ к GitHub: публичный ключ пользователя деплоя добавить в репозиторий → Settings → Deploy keys (с ✅ Allow write access).

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
# Webhook-режим (опционально; без WEBHOOK_URL бот работает в polling-режиме):
WEBHOOK_URL=https://<DOMAIN>/webhook
WEBHOOK_SECRET=<случайная строка 32+ символов>
WEBHOOK_PATH=/webhook
```

⚠️ **Важно про Spotify**: Redirect URI, отличные от `localhost`, обязаны быть `https` — иначе Spotify их отклонит. Поэтому прод требует **домен + Caddy** (уже в compose). После деплоя добавь `https://<DOMAIN>/oauth/spotify/callback` в Spotify Dashboard → Settings → Redirect URIs.

## Эксплуатация (выученные уроки)
- **Никогда `docker compose down -v` на проде**: сносит volume `pgdata` (все пользователи и интеграции) и `caddy_data` (Let's Encrypt сертификаты → TLS ляжет + rate limit на перевыпуск). Деплой-скрипт чистит только контейнеры и дублирующиеся сети, volumes не трогает.
- **Дубли сетей**: после упавших деплоев могут остаться две сети `playmystation_default` (`network ... is ambiguous`). Чинятся удалением по ID: `docker network ls --filter name=playmystation -q | xargs -r docker network rm` (уже встроено в deploy).
- **Миграции Alembic — в git**: `alembic/versions/*.py` обязаны коммититься, иначе `upgrade head` на сервере — no-op и таблиц не будет (`relation "users" does not exist`).
- **Telegram HTML**: любой динамический текст (названия треков!) и плейсхолдеры (`<provider>`, `<токен>`) экранировать (`&lt;...&gt;`, `html.escape`), иначе `Bad Request: can't parse entities` и 500 на каждый апдейт.
- **Webhook vs polling**: без `WEBHOOK_URL` бот работает в polling (входящий https не нужен). Возврат на webhook — добавить `WEBHOOK_URL`/`WEBHOOK_SECRET` в `ENV_PROD` + деплой.

## Вдохновлено и отличие от референса

Архитектурным ориентиром служит [es3n1n/nowplaying](https://github.com/es3n1n/nowplaying)
(`playinnowbot`, Apache-2.0, архив с 02.2026) — мультиплатформенный бот
(Spotify / Yandex / Last.fm / Apple / SoundCloud) с управлением воспроизведением.

Осознанно **не форкаем**, а переносим идеи в собственную кодовую базу:
- взято как образец: богатый интерфейс платформы (флаги возможностей + `play/queue/like`),
  Last.fm как источник данных, Ynison для честного realtime Яндекса, кеш треков через
  Telegram-канал, матчинг через `song.link`;
- **спортировано дословно** (Apache-2.0, с указанием авторства): Go-прокси `ynison-proxy/`,
  сгенерированные protobuf-модули `app/services/ynison/pyproto/`, протокол обмена
  в `app/services/ynison/client.py` — клиент адаптирован под наши настройки/логи;
- не берём: закрытый µdownloader (скачивание с YouTube — не опенсорс по юридическим
  причинам), собственный сервер Bot API, frontend + браузерное расширение для авторизации;
- уже лучше референса: мультиаккаунтный ALL-режим, recently-played фолбэки,
  dual polling/webhook, русская локализация сообщений.

### Почему нет скачивания полных треков (uDownloader, yt-dlp)

Оценено: открытый [uDownloader](https://github.com/bolablg/uDownloader) (MIT) — это
враппер над `yt-dlp`, технически связка «`song.link`-матчинг → yt-dlp → кеш в Telegram-канале»
реализуема. Решение: **не делаем** — скачивание с YouTube нарушает его ToS, риски
(жалобы правообладателей, бан Bot-токена) несёт владелец VPS/бота. Вместо этого —
только легальное: 30-секундные `preview_url` Spotify.
Пересмотреть можно осознанным решением владельца.

## Карта разработки
См. [ROADMAP.md](./ROADMAP.md).
