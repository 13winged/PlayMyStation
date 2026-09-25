# 🗺️ Карта разработки PlayMyStation

## Легенда статусов
- ✅ Готово · 🔄 В работе · ⬜ Запланировано

## Milestone 0 — MVP scaffold ✅
- [x] Модели `users` + `integrations` (UniqueConstraint user+provider)
- [x] `BaseMusicService` + `TrackDTO` + 3 стратегии + `factory.resolve_now_playing()`
- [x] Бот: `/start /services /now /np /yandex`, inline-статусы, выбор `active_provider/all`
- [x] FastAPI OAuth callbacks Spotify/SoundCloud, шифрование токенов (Fernet)
- [x] `docker-compose`: postgres + redis + app; `app/main.py` (polling + uvicorn)

## Milestone 1 — Auth & надежность ✅
- [x] Alembic-миграции (применяются при старте; миграции трекаются в git)
- [x] RedisStorage для FSM + кеш `now_playing` ~20 сек (защита от спама /now)
- [x] Обработка Spotify 429/expired: ретраи httpx (backoff + `Retry-After`), circuit-breaker
- [x] Удаление сообщений с Яндекс-токеном + команда `/disconnect <provider>`
- [x] Тесты: `track_card` (в т.ч. экранирование HTML), `factory` (моки сервисов), репозитории (sqlite+aiosqlite) — 34 passed

## Milestone 2 — UX
- [ ] Кнопки ⏯ ⏭ ⏮ (Spotify API control) + автообновление карточки /now каждые N сек
- [ ] Обложка трека + ссылка-кнопка, история «последние 10 треков» (Redis list на юзера)
- [ ] Уведомления «друг слушает»: подписки на друзей, дайджест
- [ ] Локализация RU/EN

## Milestone 4 — По мотивам es3n1n/nowplaying (свой код, не форк)
- [x] **Last.fm-провайдер** (`user.getrecenttracks`, только username + API key) — рабочий `/now` для free-юзеров без Premium где бы то ни было
- [ ] **Флаги возможностей платформы** (`PLAY/LIKE/QUEUE`) — эволюция `BaseMusicService` под управление воспроизведением
- [ ] **Ynison-realtime для Яндекса** — портировать gRPC-клиент нативного протокола вместо эвристики по очереди
- [ ] **song.link-матчинг** — кнопки «открыть этот же трек на …» в карточке
- [ ] **Кеш аудио через Telegram-канал** — скачанное отправляется в приватный канал, повторная отдача по `file_id`
- [ ] Скачивание полных треков — **отклонено**: оценён открытый uDownloader/yt-dlp
  (`song.link`-матчинг → yt-dlp → кеш-канал), но скачивание с YouTube нарушает его ToS,
  риски несёт владелец. Остаёмся на легальном: Spotify `preview_url` + SoundCloud
  `download_url` (подробности в README). Пересмотр — только осознанным решением владельца

## Milestone 3 — Продакшн
- [x] Webhook-режим (сертификат, секрет) + dual polling/webhook + graceful shutdown
- [x] CI (ruff/pytest/docker build) + CD на VPS через GitHub Actions (SSH + Deploy Key) + Caddy (https)
- [ ] Метрики Prometheus + Sentry, структурированные логи (structlog)
- [ ] Бэкапы Postgres
- [ ] Ротация Fernet-ключей, audit-log подключений

## Текущий статус прода (2026-09-25)
- Бот работает в **polling-режиме** (временно).
- Webhook отключён до **2026-09-27 00:54 UTC**: Let's Encrypt rate limit (5 сертификатов/нед — съедены перевыпусками после `down -v`). Возврат: добавить `WEBHOOK_URL`/`WEBHOOK_SECRET` в `ENV_PROD` + деплой.
- Прод: `https://hissihyss2.com`, Caddy + авто-https, PostgreSQL + Redis в compose.

## Риски
1. Яндекс: неофициальный API, токены короткоживущие → вынести в отдельный воркер с `asyncio.to_thread`.
2. SoundCloud: нет realtime → честный UX «последний трек», не обещать live.
3. Spotify: квоты/скоупы → запрашивать минимум (`user-read-currently-playing user-read-playback-state`).
4. Деплой: не использовать `down -v` (сносит БД и сертификаты); миграции Alembic всегда коммитить.
