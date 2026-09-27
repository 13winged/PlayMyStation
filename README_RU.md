<div align="center">

# 🎵 PlayMyStation

**Один `/now` на всю музыку — Spotify, Яндекс Музыка, YouTube Music и Last.fm в одном Telegram-боте.**

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-8B2BE6?style=flat-square)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](./pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)](./docker-compose.yml)
[![CI](https://github.com/13winged/PlayMyStation/actions/workflows/ci.yml/badge.svg)](https://github.com/13winged/PlayMyStation/actions)
[![Ruff](https://img.shields.io/badge/ruff-checked-ef3939?style=flat-square)](./pyproject.toml)

> 🇬🇧 English version: [README.md](./README.md)

</div>

---

## Демо

```
/now
```

```
▶️ YouTube Music — ⏸️ Последний трек
Pretty Boy (feat. Lil Yachty)
Joji
2:38
🔗 Открыть трек
[ ▶️ YouTube Music ] [ 🔴 Яндекс Музыка ] [ 🟢 Spotify ]
[ ⏬ Превью (30 сек) ]
[ ⚙️ Мои сервисы ]
🎵 <аудиофайл следом>
```

Карточка в духе Spotify-плеера, кнопки платформ и само аудио —
всё автоматически, фоном, best-effort.

---

## Возможности

| Область | Что |
|---|---|
| **`/now` (`/np`)** | Опрос активного сервиса — или всех сразу (режим ALL, приоритет реально играющему) |
| **Аудио** | Полный трек следом за карточкой: Яндекс — прямые ссылки, YouTube — `yt-dlp`, Spotify/Last.fm — YouTube-матчинг; кеш `file_id` = мгновенные повторы |
| **Управление** | ⏸/▶️/⏭/⏮/❤️ под Spotify-карточками (нужны Premium + активное устройство) |
| **Ссылки** | Ссылка на трек из чата и групп → карточка + аудио (одна закачка на юзера) |
| **Кросс-ссылки** | Кнопки «этот же трек на …» через нативный матчинг с проверкой длительности |
| **Аккаунты** | До 4 привязок, переключение активного, `/disconnect` |
| **Языки** | RU/EN через `/lang` |
| **Эксплуатация** | Prometheus `/metrics`, `/health` + `/ready`, Sentry, JSON-логи, бэкапы Postgres, audit-log |

---

## Провайдеры (честно)

| Провайдер | Сейчас играет | Аудио | Привязка |
|---|---|---|---|
| 🟢 **Spotify** | realtime API — нужен Premium на аккаунте-**владельце** приложения, иначе 403 всем | полный трек через YouTube-матчинг, фолбэк 30-сек preview | OAuth |
| 🔴 **Яндекс Музыка** | realtime (Ynison) / фолбэк очередь | полный трек (mp3/aac) | токен |
| ▶️ **YouTube Music** | история (`get_history`) | полный трек (m4a) | OAuth device-flow (ссылка + код) или заголовки |
| 🟪 **Last.fm** | скроббл (флаг `nowplaying`) — выход для free-юзеров Spotify | через YouTube-матчинг | username (без OAuth) |

---

## Команды

| Команда | Что |
|---|---|
| `/start` | Онбординг + сервисы |
| `/services` | Подключить / выбрать сервис |
| `/now`, `/np` | Что играет (+ аудио) |
| `/spotify`, `/yandex`, `/youtube`, `/lastfm` | Выбрать режим — или подключить, если не привязан |
| `/lang` | RU/EN |
| `/disconnect <provider>` | Отвязать |
| *ссылка на трек в чате* | Скачать + прислать (в группах: ссылка, `@упоминание` + ссылка, реплай со ссылкой) |

---

## Быстрый старт

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

Тесты: `python -m pytest -q` (200) · Линтер: `ruff check app tests`

---

## Архитектура

| Слой | Файлы |
|---|---|
| Стратегии провайдеров | `app/services/spotify\|yandex\|youtube\|lastfm.py` — `BaseMusicService` + `TrackDTO`, фабрика с ALL-режимом, bulkhead-таймауты, circuit breakers |
| Realtime Яндекса | `app/services/ynison/` + `ynison-proxy/` — нативный gRPC + Go-сайдкар |
| Бот | `app/bot/` — хэндлеры, клавиатуры, `track_card()`, RU/EN (`i18n.py`), доставка аудио (`delivery.py`) |
| Web | `app/web/` — OAuth-callback Spotify (CSRF-state), `/health`, `/ready`, `/metrics`, вебхук Telegram (секрет обязателен) |
| Ядро | `app/core/` — конфиг, БД, Redis, retry, метрики, Sentry/structlog, шифрование токенов (Fernet + ротация), audit-log |

---

## Свой сервер

Полный гайд — сервер, OAuth-приложения, деплой, бэкапы, мониторинг, troubleshooting:
**[README_FOR_YOUR_SERVER.md](./README_FOR_YOUR_SERVER.md)**

---

## FAQ

**`/now` молчит по Spotify, в логах `403 … owner of the app`?**
Realtime требует Premium на аккаунте-**владельце** приложения — для всех юзеров,
включая премиумных. Разблокировка — до нескольких часов после оформления.

**YouTube отдаёт пустую историю, хотя музыка играет?**
Привязка смотрит не в тот профиль: приостановленная история
(`myactivity.google.com`), другой Google-аккаунт или brand-аккаунт.
Перепривяжись (`/youtube`) из нужного профиля.

**Скачивание падает с `cookies are no longer valid`?**
Google ротирует куки — перепривяжи свежими заголовками, а лучше добей OAuth
(тест-юзеры в Google Cloud Console). Бот подскажет сам.

**`Sign in to confirm you're not a bot`?**
Закрыто: куки юзера + tv/web-клиенты + EJS-солвер с Node 22 в образе.
Если persists — IP дата-центра в жёстком списке, проксируй YT-трафик.

**Только MP3, без FLAC с Яндекса?**
Осознанно: большинство FLAC не влезают в лимиты Telegram; берётся MP3 320,
превью-варианты пропускаются.

---

## Карта разработки

- [ROADMAP.md](./ROADMAP.md) — Telegram-бот
- [ROADMAP_DISCORD.md](./ROADMAP_DISCORD.md) — план Discord-зеркала

---

## Контрибьютинг

Issues и PR приветствуются. Стек: Python 3.11+, aiogram, FastAPI, PostgreSQL, Redis.
`ruff` + `pytest` должны оставаться зелёными. Доки на двух языках — держать в синхроне.

---

## Лицензия

[Apache-2.0](./LICENSE) — см. [LICENSE](./LICENSE).

Вдохновлено [es3n1n/nowplaying](https://github.com/es3n1n/nowplaying)
(`playinnowbot`, Apache-2.0): флаги возможностей, Last.fm как источник,
Ynison-realtime, кеш аудио. Go-прокси и protobuf-модули спортированы дословно
(с указанием авторства), остальное — свой код.

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=13winged/PlayMyStation&type=date)](https://www.star-history.com/?type=date&repos=13winged/PlayMyStation)
