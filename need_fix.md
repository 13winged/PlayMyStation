# 📋 PlayMyStation — Список ошибок и улучшений (Аудит)

> Сгенерировано автоматически после полного аудита кодовой базы.  
> Статус: **Открыто** — требуется ревью и планирование.

---

## 🔴 Критические ошибки (блокеры для продакшена)

### 1. Race condition в `EnsureUserMiddleware` — двойной commit, инконсистентность БД
**Файл:** `app/bot/middlewares.py:39-54`  
**Проблема:** Middleware делает `await session.commit()`, хэндлеры тоже коммитят → вложенные транзакции (SQLAlchemy async не поддерживает savepoints без `begin_nested()`). При ошибке в хэндлере — пользователь уже создан, но остальные изменения откатятся.  
**Исправление:** Убрать commit из middleware, использовать `flush()`. В `DbSessionMiddleware` добавить автокоммит/откат в `try/except`.

```python
# EnsureUserMiddleware
await session.flush()  # вместо commit()

# DbSessionMiddleware
async with self._factory() as session:
    data["session"] = session
    try:
        result = await handler(event, data)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
```

---

### 2. Circuit Breaker не thread-safe
**Файл:** `app/core/retry.py:16-72`  
**Проблема:** `is_open` property читает/пишет `_state` и `_failures` без лока при параллельных вызовах (`asyncio.gather` в `resolve_now_playing`).  
**Исправление:** Весь доступ к состоянию под `asyncio.Lock` (вынести проверку в `async def check_open()`).

---

### 3. Yandex Music: `asyncio.to_thread()` создаёт поток на каждый вызов — thread explosion
**Файл:** `app/services/yandex.py:76-81, 96-138`  
**Проблема:** При спаме `/now` или параллельных юзерах — OOM от неограниченного пула потоков. `yandex_music.Client` не thread-safe.  
**Исправление:** Вынести в `ThreadPoolExecutor(max_workers=4)` с лимитом, либо переписать на асинхронный клиент.

---

### 4. DEV-фолбэк в шифровании (`security.py`) — токены в plaintext без FERNET_KEY
**Файл:** `app/core/security.py:42-62`  
**Проблема:** Если `FERNET_KEY=CHANGE_ME` или не задан — токены пишутся в БД **в открытом виде**.  
**Исправление:** Жёстко требовать валидный ключ при старте, падать с `RuntimeError` если ключ невалиден/пустой.

```python
def _get_fernets() -> list[Fernet]:
    settings = get_settings()
    primary = _parse_keys(settings.fernet_key)
    if not primary or settings.fernet_key == "CHANGE_ME":
        raise RuntimeError("FERNET_KEY must be a valid 44-byte URL-safe base64 key")
    return primary + _parse_keys(settings.fernet_keys_old)
```

---

### 5. Spotify / Last.fm: глобальные httpx-клиенты без proper lifecycle
**Файлы:** `app/services/spotify.py:27-53`, `app/services/lastfm.py:23-49`  
**Проблема:** Глобальные синглтоны — сложно тестировать, нет graceful shutdown при падении процесса до `shutdown_resources()`.  
**Исправление:** Перенести в `lifespan` FastAPI или DI через `HttpClientManager` с `@asynccontextmanager`.

---

### 6. OAuth state без CSRF-защиты — только `telegram_id`
**Файл:** `app/web/oauth.py:22-53`  
**Проблема:** `state` должен быть непредсказуемым токеном с TTL в Redis, привязанным к сессии. Злоумышленник может подсунуть свой `state` и привязать чужой аккаунт.  
**Исправление:** Генерировать `secrets.token_urlsafe(32)`, хранить в Redis с TTL 10 мин, верифицировать при callback.

---

## 🟠 Предупреждения (требуют внимания до релиза)

### 7. Yandex / YouTube / Last.fm: нет retry transport для HTTP-клиентов
**Файлы:** `app/services/yandex.py`, `app/services/youtube.py`, `app/services/lastfm.py`  
Только у Spotify есть `create_retry_transport()` + circuit breaker. Остальные — голые вызовы без ретраев на 429/5xx.  
**Исправление:** Добавить retry transport везде, где есть `httpx.AsyncClient`.

---

### 8. Redis connection: глобальный синглтон без reconnection logic
**Файл:** `app/core/redis.py:13-32`  
Нет авто-reconnect, health check, ping при получении. При разрыве — все кэши упадёт с исключением.  
**Исправление:** Добавить `health_check_interval=30`, retry wrapper, ping при `get_redis()`.

---

### 9. Webhook secret проверяется только если задан — иначе пропускается
**Файл:** `app/web/app.py:114-116`  
В проде без `WEBHOOK_SECRET` проверка **не выполняется**.  
**Исправление:** Требовать секрет в webhook-режиме:
```python
if settings.use_webhook and not settings.webhook_secret:
    raise RuntimeError("WEBHOOK_SECRET is required in webhook mode")
```

---

### 10. Alembic миграции не ждут готовности БД в Docker
**Файл:** `app/main.py:69-70`  
`depends_on` в compose не ждёт healthy.  
**Исправление:** Добавить wait-for-db с ретраями перед миграциями.

---

### 11. Docker: запуск от root, нет non-root пользователя
**Файл:** `Dockerfile:1-27`  
Контейнер запускается от `root` — риск privilege escalation.  
**Исправление:** Добавить `USER appuser` после создания пользователя в Dockerfile.

---

### 12. PostgreSQL пароль в plain text в `docker-compose.yml`
**Файл:** `docker-compose.yml:5-7`  
```yaml
POSTGRES_PASSWORD: playmystation  # Хардкод
```
**Исправление:** Использовать `${POSTGRES_PASSWORD}` из `.env`.

---

### 13. Yandex токен в чате (`/yandex <token>`) — риск утечки в логах Telegram
**Файл:** `app/bot/handlers/yandex_auth.py:32-82`  
Сообщение с токеном видно до удаления, в логах Telegram серверов.  
**Исправление:** Требовать отправку в личку боту, использовать WebApp для ввода токена.

---

### 14. yt-dlp скачивание: нет лимита одновременных закачек — риск OOM/CPU
**Файл:** `app/services/youtube.py:234-280`  
`_download_youtube_sync` запускается в `asyncio.to_thread()` без семафора. Несколько пользователей могут параллельно качать 45МБ треки.  
**Исправление:** Добавить `asyncio.Semaphore(2-3)` на уровне модуля для закачек.

---

### 15. Spotify client credentials токен кэшируется в памяти — не инвалидируется при ротации ключей
**Файл:** `app/services/crosslink.py:27-91`  
Если сменятся `SPOTIFY_CLIENT_ID/SECRET` — старый токен будет использоваться до истечения TTL.  
**Исправление:** Добавить версионирование или инвалидацию при старте/релоаде конфига.

---

### 16. Cross-platform матчинг: `pick_by_duration` может вернуть не тот трек (кавер/лайв)
**Файл:** `app/services/crosslink.py:40-60`  
Совпадение только по длительности (±7с) — кавер/remix с той же длительностью пройдёт.  
**Рекомендация:** Добавить fuzzy matching по артисту/названию (Levenshtein) + ISRC если доступен.

---

### 17. Audit log: `detail` может случайно утечь секреты
**Файл:** `app/db/repositories.py:106-127`  
Нет валидации что в `detail` не попал токен.  
**Рекомендация:** Добавить санитизацию или запрет на длинные строки (>128 chars).

---

## 🟢 Улучшения / Рефакторинг (техдолг)

### 18. Progress bar баг при `progress_ms=0`
**Файл:** `app/bot/formatters.py:15-21`  
`0` считается falsy — бар пустой. UX: начало трека показывает `--:-- / 3:00` без бара.  
**Исправление:** Явная проверка `progress_ms is None`.

---

### 19. Кэш `now_playing` в Redis: сериализация через `__dict__` + `default=str`
**Файл:** `app/core/redis.py:53-63`  
Хрупко при изменении `TrackDTO`.  
**Исправление:** `dataclasses.asdict(track)` или `model_dump()`.

---

### 20. Graceful shutdown для polling mode не обрабатывает SIGTERM
**Файл:** `app/main.py:129-136`  
В `run_polling` нет `stop_event` + signal handler. При `docker stop` — SIGKILL через 10с без закрытия сессий.  
**Исправление:** Добавить signal handling как в `run_webhook_mode`.

---

### 21. `extra="ignore"` в Settings — тихие опечатки в `.env`
**Файл:** `app/core/config.py:12`  
`SPOTFY_CLIENT_ID` вместо `SPOTIFY_CLIENT_ID` — молча игнорируется.  
**Исправление:** `extra="forbid"` в проде или startup-валидация обязательных полей.

---

### 22. Алембик миграции в `.gitignore` — не попадают в репозиторий
**Файл:** `.gitignore:6`  
```gitignore
alembic/versions/*.py
```
На другом окружении `alembic upgrade head` не сработает.  
**Исправление:** Убрать из `.gitignore`.

---

### 23. Нет pre-commit хуков (ruff, mypy, tests)
**Рекомендация:** Добавить `.pre-commit-config.yaml` с ruff, ruff-format, mypy.

---

### 24. Hardcoded scopes в Spotify auth
**Файл:** `app/services/spotify.py:58-61`  
Вынести в конфигурацию (`config.py`).

---

### 25. Caddyfile: нет security headers (HSTS, CSP, etc.)
**Файл:** `Caddyfile:1-3`  
Добавить `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`.

---

### 26. GitHub Actions deploy: hardcoded репо
**Файл:** `.github/workflows/deploy.yml:36,39`  
`git@github.com:13winged/PlayMyStation.git` — нельзя форкнуть без правки.  
**Исправление:** Использовать `${{ github.repository }}`.

---

### 27. Верхние границы зависимостей блокируют security updates
**Файл:** `pyproject.toml:7-11`  
`"aiogram>=3.13,<4"` — использовать `~=` или только нижние границы + Dependabot.

---

### 28. Type hints: много `Any`, `# type: ignore`, `noqa: BLE001`
**Рекомендация:** Включить `mypy` в CI, пофиксить типы, заменить `BLE001` на конкретные исключения где возможно.

---

### 29. Ynison Go-прокси: нет health check, метрик, graceful shutdown
**Файл:** `ynison-proxy/main.go`  
Простой gRPC прокси без observability.  
**Рекомендация:** Добавить `/health`, Prometheus metrics, graceful shutdown.

---

### 30. Тесты: нет интеграционных тестов OAuth flow, webhook, реальных API
Только unit тесты с моками.  
**Рекомендация:** Добавить contract тесты (VCR.py / pytest-httpx) для OAuth callbacks, webhook endpoint, внешних API.

---

## 📋 План действий (приоритеты)

| Приоритет | Задачи |
|-----------|--------|
| **P0 — Срочно (сегодня)** | #1, #2, #3, #4, #5, #6 |
| **P1 — На этой неделе** | #7, #8, #9, #10, #11, #12, #13, #14, #15 |
| **P2 — В спринте** | #16, #17, #18, #19, #20, #21, #22 |
| **P3 — Техдолг** | #23, #24, #25, #26, #27, #28, #29, #30 |

---

## 🔗 Связанные файлы для быстрого доступа

- `app/bot/middlewares.py` — #1
- `app/core/retry.py` — #2
- `app/services/yandex.py` — #3, #7
- `app/core/security.py` — #4
- `app/services/spotify.py` — #5, #24
- `app/services/lastfm.py` — #5, #7
- `app/web/oauth.py` — #6
- `app/core/redis.py` — #8
- `app/web/app.py` — #9
- `app/main.py` — #10, #20
- `Dockerfile` — #11
- `docker-compose.yml` — #12
- `app/bot/handlers/yandex_auth.py` — #13
- `app/services/youtube.py` — #7, #14
- `app/services/crosslink.py` — #15, #16
- `app/db/repositories.py` — #17
- `app/bot/formatters.py` — #18
- `app/core/config.py` — #21
- `.gitignore` — #22
- `Caddyfile` — #25
- `.github/workflows/deploy.yml` — #26
- `pyproject.toml` — #27
- `ynison-proxy/main.go` — #29

---

> **Примечание:** Этот файл создан для отслеживания. Каждый пункт можно превратить в отдельный Issue/PR с ссылкой на этот документ.