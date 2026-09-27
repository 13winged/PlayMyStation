# 🎵 PlayMyStation

> 🇬🇧 English version: [README.md](./README.md)

Асинхронный мультиаккаунтный Telegram-бот: **Spotify + Яндекс Музыка + YouTube Music + Last.fm** в одном `/now` — карточка трека, аудио рядом, кнопки управления.

## Возможности

- `/now` (`/np`) — что играет: опрос активного сервиса или всех сразу (режим ALL, приоритет реально играющему), карточка в духе Spotify-плеера + аудио следом
- Кнопки под карточкой: ⏸/▶️/⏭/⏮/❤️ для Spotify, «этот же трек на …» (кросс-матчинг), «⏬ Превью», «Мои сервисы»
- Ссылки из чата (и групп): ссылка на трек Spotify/Яндекс/YouTube → карточка + аудио
- `/services` — подключение до 4 аккаунтов, выбор активного; команды `/spotify /yandex /youtube /lastfm` переключают режим, если сервис привязан
- Ссылки на треки Spotify/Яндекс/YouTube прямо из чата и групп → карточка + аудио
- `/lang` — RU/EN, `/disconnect` — отвязка
- Метрики Prometheus (`/metrics`), пробы `/health` + `/ready`, Sentry опционально

## Стек

Python 3.11+ · aiogram 3.x · FastAPI · SQLAlchemy 2.0 Async + PostgreSQL · Redis ·
httpx · yandex-music · ytmusicapi · yt-dlp · Docker Compose

## Быстрый старт (локально)

```bash
cp .env.example .env        # заполнить BOT_TOKEN, FERNET_KEY
docker compose up --build
# бот: polling (или webhook, если задан WEBHOOK_URL); web: http://localhost:8000/health
# Миграции Alembic применяются сами при старте
```

Без Docker:

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e .[dev]
python -m app.main
```

Тесты: `python -m pytest -q` (200), линтер: `ruff check app tests`.

## Провайдеры (честно)

| Провайдер | Сейчас играет | Аудио | Привязка |
|---|---|---|---|
| Spotify | realtime API (нужен Premium владельца приложения, иначе 403) | полный через YouTube-матчинг, фолбэк 30-сек preview | OAuth |
| Яндекс Музыка | realtime (Ynison) / очередь | полный трек | токен |
| YouTube Music | история | полный трек | OAuth device-flow / заголовки |
| Last.fm | скроббл (`nowplaying`) | через YouTube-матчинг | username |

Подробности ограничений — в [гайде по серверу](./README_FOR_YOUR_SERVER.md).

## Архитектура (кратко)

- `app/services/` — стратегии провайдеров (`BaseMusicService` + `TrackDTO`), фабрика с ALL-режимом, bulkhead-таймауты, circuit breakers
- `app/services/ynison/` + `ynison-proxy/` — realtime Яндекс Музыки (gRPC + Go-сайдкар)
- `app/bot/` — хендлеры, клавиатуры, `track_card()`, RU/EN (`i18n.py`), доставка аудио (`delivery.py`)
- `app/web/` — FastAPI: OAuth-callback Spotify (CSRF-state), `/health`, `/ready`, `/metrics`, Telegram webhook (секрет обязателен)
- `app/core/` — конфиг, БД, Redis, retry, метрики, Sentry/structlog, шифрование токенов (Fernet + ротация), audit-log

## Документы

- [README_FOR_YOUR_SERVER.md](./README_FOR_YOUR_SERVER.md) — поднятие у себя: сервер, OAuth-приложения, деплой, бэкапы, мониторинг, troubleshooting
- [ROADMAP.md](./ROADMAP.md) — карта разработки
- [`.env.example`](./.env.example) — все переменные с комментариями
- [LICENSE](./LICENSE) — Apache-2.0

## Вдохновлено

Архитектурный ориентир — [es3n1n/nowplaying](https://github.com/es3n1n/nowplaying)
(`playinnowbot`, Apache-2.0): идеи флагов возможностей, Last.fm как источника,
Ynison-realtime и кеша аудио. Go-прокси `ynison-proxy/` и protobuf-модули
спортированы дословно (Apache-2.0, с указанием авторства), остальное — свой код.
