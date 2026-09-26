# 🗺️ Карта разработки PlayMyStation

## Легенда статусов
- ✅ Готово · 🔄 В работе · ⬜ Запланировано

## Milestone 0 — MVP scaffold ✅
- [x] Модели `users` + `integrations` (UniqueConstraint user+provider)
- [x] `BaseMusicService` + `TrackDTO` (+`preview_url`) + 4 стратегии + `factory.resolve_now_playing()` + bulkhead-таймауты + circuit-breakers
- [x] Бот: `/start /services /now /np /yandex /spotify /youtube /lastfm`, inline-статусы, выбор `active_provider/all`, кнопка «⏬ Превью», удаление секретов из чата
- [x] FastAPI OAuth callback Spotify, шифрование токенов (Fernet)
- [x] `docker-compose`: postgres + redis + app; `app/main.py` (polling + uvicorn)

## Milestone 1 — Auth & надежность ✅
- [x] Alembic-миграции (применяются при старте; миграции трекаются в git)
- [x] RedisStorage для FSM + кеш `now_playing` ~20 сек (защита от спама /now)
- [x] Обработка Spotify 429/expired: ретраи httpx (backoff + `Retry-After`), circuit-breaker
- [x] Удаление сообщений с Яндекс-токеном + команда `/disconnect <provider>`
- [x] Тесты: `track_card` (в т.ч. экранирование HTML), `factory` (моки + таймауты), репозитории (sqlite+aiosqlite), Spotify-фолбэк, Last.fm, Ynison, парсинг `/spotify`/`/yandex` — 59 passed

## Milestone 2 — UX
- [ ] Кнопки ⏯ ⏭ ⏮ (Spotify API control) + автообновление карточки /now каждые N сек
- [x] Обложка трека + ссылка-кнопка в карточке
- [ ] История «последние 10 треков» (Redis list на юзера)
- [ ] Уведомления «друг слушает»: подписки на друзей, дайджест
- [ ] Локализация RU/EN

## Milestone 4 — По мотивам es3n1n/nowplaying (свой код, не форк)
- [x] **Last.fm-провайдер** (`user.getrecenttracks`, только username + API key) — рабочий `/now` для free-юзеров без Premium где бы то ни было
- [ ] **Флаги возможностей платформы** (`PLAY/LIKE/QUEUE`) — эволюция `BaseMusicService` под управление воспроизведением
- [x] **Ynison-realtime для Яндекса** — спортирован gRPC-клиент нативного протокола + Go-сайдкар `ynison` в compose (realtime-трек + прогресс, фолбэк на эвристику очереди). Проверено на проде 2026-09-26: карточка с прогресс-баром `0:55 / 2:38`
- [x] **Докачка аудио в /now** (решение владельца 2026-09-26, риски ToS приняты): Яндекс — полный трек по токену, YouTube — `yt-dlp` m4a, Spotify — 30-сек preview, Last.fm — ничего; кап 45 МБ, фоном best-effort
- [ ] **song.link-матчинг** — кнопки «открыть этот же трек на …» в карточке
- [ ] **Кеш аудио через Telegram-канал** — скачанное отправляется в приватный канал, повторная отдача по `file_id`
- [ ] Скачивание полных треков — **включено решением владельца 2026-09-26**
  (см. README «Скачивание треков в /now»); uDownloader как отдельный сервис больше не рассматривается

## Milestone 3 — Продакшн
- [x] Webhook-режим (сертификат, секрет) + dual polling/webhook + graceful shutdown
- [x] CI (ruff/pytest/docker build) + CD на VPS через GitHub Actions (SSH + Deploy Key) + Caddy (https)
- [ ] Метрики Prometheus + Sentry, структурированные логи (structlog)
- [ ] Бэкапы Postgres
- [ ] Ротация Fernet-ключей, audit-log подключений

## Текущий статус прода (2026-09-26)
- Бот работает в **polling-режиме** (временно).
- Webhook отключён до **2026-09-27 00:54 UTC**: Let's Encrypt rate limit (5 сертификатов/нед — съедены перевыпусками после `down -v`). Возврат: добавить `WEBHOOK_URL`/`WEBHOOK_SECRET` в `ENV_PROD` + деплой.
- ✅ Проверено на проде: **Last.fm** (`/now` → карточка с обложкой, `nowplaying`-статус) и **Яндекс через Ynison** (карточка с реальным прогресс-баром).
- ⏳ Spotify ждёт Premium на аккаунте-владельце приложения (иначе `403` на все user-запросы).
- Прод: `https://hissihyss2.com`, Caddy + авто-https, PostgreSQL + Redis + Ynison-прокси в compose.

## Риски
1. Яндекс: неофициальный API + reverse-engineered Ynison — может сломаться при изменениях у Яндекса (фолбэк на очередь остаётся); токены короткоживущие.
2. YouTube Music: нет realtime → честный UX «последний трек», не обещать live; browser-auth кука живёт ~2 года.
3. Spotify: dev-mode требует Premium владельца + allowlist до 5 юзеров; скоупы `currently-playing + playback-state + recently-played`.
4. Деплой: не использовать `down -v` (сносит БД и сертификаты); миграции Alembic всегда коммитить.
