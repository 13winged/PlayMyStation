# 🤖 PlayMyStation для Discord — Roadmap

Зеркало Telegram-бота: тот же `/now` (Spotify / Яндекс / YouTube Music / Last.fm),
карточки, аудио, кнопки — но в Discord-UX (slash-команды, embeds, attachments).
Голосовые каналы (проигрывание в войс) — **вне скоупа v1** (там Lavalink и
совсем другая архитектура).

## Что переиспользуем как есть (без изменений)

- Все 4 стратегии (`app/services/spotify|yandex|youtube|lastfm.py`), фабрика
  с ALL-режимом, bulkhead-таймауты, circuit breakers
- `crosslink.py` (матчинг), `audio.py` (капы — см. ограничение 25 МБ ниже),
  `songlink`-наследие не нужно
- OAuth-колбэки (`app/web/oauth.py`) — state уже `id:token`, добавляется
  префикс платформы: `discord:<id>:<token>`
- Redis-кеши (`now_playing`, `file_id`, кросслинки, локи), метрики Prometheus,
  Fernet-стек, audit-log, Alembic-подход к миграциям
- `yt-dlp` + EJS + node, Ynison-прокси, backup-сервис

## Что придётся переделать

### 1. Пользователи: платформа вместо telegram_id
`users.telegram_id` захардкожен везде. Вариант без боли:
миграция `users.platform TEXT DEFAULT 'telegram'` + `platform_user_id BIGINT`,
unique(`platform`, `platform_user_id`), данные `telegram_id` → перенос.
Репозитории принимают `platform` параметром. Оценка: 0.5–1 день + тесты.

### 2. Discord-слой (`app/discord/`, новый)
- `discord.py` v2, **только slash-команды**: `/now /services /connect /disconnect /lang`
  (префикс-команды в Discord мертвы — не делать)
- Embed вместо карточки: cover → `thumbnail`, прогресс — та же текстовая строка
  (`1:00 ──●── -1:38` рендерится моноширинным в `code`-блоке description)
- Кнопки → `discord.ui.View`: управление Spotify, «этот же трек на …» (link-кнопки),
  превью. Persistent views не обязательны (экспирируем за ненадобностью)
- Ответы по умолчанию **публичные** в канале; ошибки привязки — `ephemeral=True`
- Привязки: Spotify OAuth (тот же колбэк), Yandex-токен — через DM (в канале
  секрет светить нельзя — удалять нельзя, только DM), YouTube — OAuth device-flow
  (заголовки через модалку не влезут: лимит ~4000 символов)
- Ссылки из чата: нужен **привилегированный `message_content` intent**
  (для приватного бота ок; для верификации на 100+ серверах — аппрув)

### 3. Лимит вложений 25 МБ (было 50 МБ в Telegram)
`MAX_TRACK_BYTES` → 23 МБ для Discord-доставки, предпочитать m4a/aac.
FLAC и длинные миксы — мимо по дизайну. Кеш `file_id` → кеш постов:
тот же приватный канал-склад, но хранить `message_id`+`attachment.url`
(или так же приватный Discord-канал + Redis-маппинг — механика 1-в-1).

### 4. Деплой рядом
Тот же образ, другой entrypoint: `python -m app.discord.main`
(или `BOT_MODE=discord`). Отдельный сервис `discord-bot` в compose:
те же postgres/redis/сеть, свой `DISCORD_TOKEN`, метрики на отдельном
`METRICS_PORT` (процессы разные — общий `/metrics` не разделить).

## Milestones

- **D0 — scaffold (1–2 дня):** discord.py, `/ping`, `/now` через существующую
  фабрику, embed-карточка, миграции `platform_*`, тесты маппинга DTO→embed
- **D1 — привязки (2–3 дня):** Spotify OAuth (state с префиксом), Yandex DM-токен,
  YouTube device-flow, `/services` + `/disconnect`, i18n переиспользуем
- **D2 — аудио (2 дня):** доставка через `delivery.py` (обобщить с Telegram),
  кап 23 МБ, канал-склад, ссылки из чата (message_content intent)
- **D3 — паритет UX (2–3 дня):** кнопки управления, кросс-ссылки, `/lang`,
  кнопки-переключатели провайдеров, метрики/пробы, доки в README_FOR_YOUR_SERVER
- **D4 — позже/опционально:** история треков, уведомления друзей,
  войс-проигрывание (Lavalink — отдельный проект по сути)

## Риски

1. `message_content` — привилегированный intent; пока бот приватный — ок
2. 25 МБ режут длинные треки сильнее, чем в Telegram — честно писать в UX
3. Два фронтенда (TG + DS) на одну БД интеграций: UniqueConstraint
   `user+provider` остаётся в силе внутри платформы; кросс-платформенных
   коллизий нет по дизайну (разные строки юзеров)
4. OAuth-клиенты Google/Spotify общие — redirect URI один, state различает
   платформу (уже заложено)
