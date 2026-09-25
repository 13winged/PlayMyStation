# 🗺️ Карта разработки PlayMyStation

## Легенда статусов
- ✅ Готово (этот scaffold) · 🔄 В работе · ⬜ Запланировано

## Milestone 0 — MVP scaffold ✅
- [x] Модели `users` + `integrations` (UniqueConstraint user+provider)
- [x] `BaseMusicService` + `TrackDTO` + 3 стратегии + `factory.resolve_now_playing()`
- [x] Бот: `/start /services /now /np /yandex`, inline-статусы, выбор `active_provider/all`
- [x] FastAPI OAuth callbacks Spotify/SoundCloud, шифрование токенов (Fernet)
- [x] `docker-compose`: postgres + redis + app; `app/main.py` (polling + uvicorn)

## Milestone 1 — Auth & надежность 🔄
- [ ] Alembic-миграции (сейчас `create_all` для MVP)
- [ ] RedisStorage для FSM + кеш `now_playing` на 15–30 сек (защита от спама /now)
- [ ] Обработка Spotify 429/expired, ретраи httpx, circuit-breaker
- [ ] Удаление сообщений с Яндекс-токеном + команда `/disconnect <provider>`
- [ ] Тесты: `track_card`, `factory` (моки сервисов), репозитории (sqlite+aiosqlite)

## Milestone 2 — UX
- [ ] Кнопки ⏯ ⏭ ⏮ (Spotify API control) + автообновление карточки /now каждые N сек
- [ ] Обложка трека + ссылка-кнопка, история «последние 10 треков» (Redis list на юзера)
- [ ] Уведомления «друг слушает»: подписки на друзей, дайджест
- [ ] Локализация RU/EN

## Milestone 3 — Продакшн
- [ ] Webhook вместо polling (сертификат, секрет), graceful shutdown
- [ ] Метрики Prometheus + Sentry, структурированные логи (structlog)
- [x] CI (ruff/pytest/docker build) + CD на VPS через GitHub Actions + Caddy (https)
- [ ] Бэкапы Postgres
- [ ] Ротация Fernet-ключей, audit-log подключений

## Риски
1. Яндекс: неофициальный API, токены короткоживущие → вынести в отдельный воркер с `asyncio.to_thread`.
2. SoundCloud: нет realtime → честный UX «последний трек», не обещать live.
3. Spotify: квоты/скоупы → запрашивать минимум (`user-read-currently-playing user-read-playback-state`).
