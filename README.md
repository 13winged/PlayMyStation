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
- `app/services/spotify.py | yandex.py | youtube.py | lastfm.py` — 4 стратегии + `audio.py` (скачивание) + `crosslink.py` (матчинг «этот же трек на …» нативными поисками, кеш Redis 7 дней)
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
- **Яндекс** — realtime через **Ynison** (нативный протокол: трек + прогресс + пауза, проверено на проде); фолбэк — очередь (`queues_list`, без прогресса). Привязка: `/yandex <токен>`. Если API висит с серверного IP — `YANDEX_PROXY_URL=http://user:pass@host:port` (только для Яндекс-трафика).
- **YouTube Music** — нет realtime → история `get_history` через ytmusicapi, помечаем как «последний трек». Привязка: `/youtube` → OAuth device-flow (ссылка + код, без DevTools; нужны серверные `YTM_OAUTH_CLIENT_ID/SECRET`) либо fallback заголовками браузера. Скачивание: OAuth — прямой аудиопоток сессии юзера, browser-auth — `yt-dlp` с его куками (без них YouTube банит серверный IP).
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

## Мониторинг

- **Prometheus**: метрики на `GET /metrics` (`pms_bot_updates_total`,
  `pms_provider_now_playing_total{provider,result}`, `pms_now_playing_cache_total`,
  `pms_circuit_breaker_open{provider}`, HTTP-латентности). Скрапинг — любым
  Prometheus/VictoriaMetrics с таргетом на `http://<host>:8000/metrics`.
- **Sentry**: включается через `SENTRY_DSN` в `.env` (release `playmystation@<version>`,
  traces 20%, без PII). Без DSN — no-op.
- **Логи**: `LOG_FORMAT=text` (по умолчанию, читаемые) или `json` (structlog,
  для прода/Loki). Существующие `logging`-вызовы работают в обоих режимах.
- **Пробы**: `/health` (liveness, всегда 200) и `/ready` (проверяет PostgreSQL
  и Redis, 503 если недоступны) — для Docker healthcheck и балансировщиков.

## Ротация Fernet-ключей

Токены шифруются стеком ключей: `FERNET_KEY` (primary, шифрование) +
`FERNET_KEYS_OLD` через запятую (только расшифровка). Процедура:

```bash
# 1. Новый ключ
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 2. В ENV_PROD: FERNET_KEY=<новый>, FERNET_KEYS_OLD=<старый> → деплой
# 3. Перешифровать всё новым ключом (отчёт в stdout):
docker compose exec app python -m app.core.security
# 4. Убрать FERNET_KEYS_OLD → деплой
```

Подключения/отключения пишутся в таблицу `audit_log` (без секретов) и в
метрику `pms_audit_total{action,provider}`. Последние события юзера:
`recent_audit()` в репозиториях.

## Бэкапы
Сервис `backup` (образ `postgres:16-alpine`) делает `pg_dump -Fc` ежедневно
в 03:00 в volume `pgbackups`, ротация — `BACKUP_RETENTION_DAYS` суток (default 7).
Первый бэкап — сразу при старте/деплоe. Логи: `docker compose logs backup`.

Проверить дампы: `docker compose exec backup ls -la /backups`

Восстановление (осторожно — перезаписывает БД):
```bash
cd ~/playmystation
docker compose exec -T postgres pg_restore -U playmystation -d playmystation \
  --clean --if-exists < "$(docker compose exec backup ls -1 /backups/playmystation-*.dump | sort | tail -1 | tr -d '\r')"
```

Для офсайта достаточно периодически забирать файлы из volume:
`docker cp playmystation-backup-1:/backups ./pgbackups-$(date +%F)`

## Эксплуатация (выученные уроки)- **Никогда `docker compose down -v` на проде**: сносит volume `pgdata` (все пользователи и интеграции) и `caddy_data` (Let's Encrypt сертификаты → TLS ляжет + rate limit на перевыпуск). Деплой-скрипт чистит только контейнеры и дублирующиеся сети, volumes не трогает.
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

### Скачивание треков в /now (решение владельца от 2026-09-26)

Изначально скачивание полных треков было отклонено (ToS YouTube, риски бана
Bot-токена). Владелец осознанно пересмотрел решение и принял риски на себя.
Матрица `/now` (аудио присылается следом за карточкой, фоном, best-effort):

| Провайдер | Что качаем | Как |
|---|---|---|
| Яндекс Музыка | полный трек (mp3/aac) | прямые ссылки через токен юзера (его подписка) |
| YouTube Music | полный трек (m4a) | `yt-dlp` `bestaudio` с куками из привязки юзера (без них YouTube банит серверный IP), без конвертации |
| Spotify | полный трек через YouTube-матчинг | из Spotify только метаданные (как у Spotisaver), аудио ищется на YT с проверкой длительности ±7с; фолбэк — 30-сек `preview_url` |
| Last.fm | аудио через YouTube-матчинг | метаданные скроббла → первый результат поиска (длительности нет, mismatch возможен) |

Ограничения: кап 45 МБ (лимит Bot API — 50 МБ), таймаут докачки 120 сек,
неудача тихая (только лог, без спама в чат). Повторные треки отдаются
мгновенно: скачанное один раз складывается в приватный Telegram-канал
(`AUDIO_CACHE_CHANNEL_ID`, бота добавить админом), повторная выдача —
по `file_id` без перекачивания, маппинг живёт в Redis 30 дней.

## Карта разработки
См. [ROADMAP.md](./ROADMAP.md).
