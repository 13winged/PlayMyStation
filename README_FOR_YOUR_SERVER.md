# 🖥️ PlayMyStation на своём сервере

Полный гайд: VPS → домен → OAuth-приложения → `.env` → деплой → эксплуатация.
Предполагается Ubuntu + root/sudo по SSH.

## 1. Что нужно

- VPS (хватит 1 CPU / 1 ГБ RAM / 20 ГБ диска), Ubuntu 22.04+
- Домен с A-записью на IP сервера (нужен для HTTPS: OAuth Spotify и webhook)
- Аккаунты: Telegram (BotFather), Spotify Developer, Google Cloud, Last.fm

## 2. Подготовка сервера (один раз)

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER   # затем перелогиниться
sudo ufw allow 22,80,443/tcp && sudo ufw enable
git clone <твой-форк-или-репо> ~/playmystation
cd ~/playmystation
```

## 3. OAuth-приложения

### Spotify ([dashboard](https://developer.spotify.com/dashboard))

1. Create app → скопировать Client ID + Client Secret
2. Settings → Redirect URIs → добавить `https://<DOMAIN>/oauth/spotify/callback` (Save!)
3. User Management → добавить себя и тестеров (dev-режим: до ~5 юзеров без Extended Quota)

⚠️ **Критично**: realtime (`currently-playing`) и управление требуют **Premium на аккаунте-владельце приложения**. Без него все user-запросы → `403`, бот падает на фолбэки (recently-played, тоже 403 без Premium владельца). Разблокировка после оформления — до нескольких часов.

### YouTube Music (Google Cloud)

1. [console.cloud.google.com](https://console.cloud.google.com) → проект → включить **YouTube Data API v3**
2. Credentials → Create Credentials → OAuth client ID → тип **TVs and Limited Input devices**
3. Скопировать Client ID + Client Secret
4. **OAuth consent screen → Test users → добавить свой Gmail**, иначе `403 access_denied` («приложение не прошло проверку»)
5. Нюанс Testing-режима: рефреш-токены живут **7 дней** → перепривязка `/youtube` раз в неделю (лечится только верификацией приложения)

Fallback без Google-клиента: привязка заголовками браузера (`/youtube` подскажет).

### Last.fm

[last.fm/api/account/create](https://www.last.fm/api/account/create) → API key.
Юзернейм вводит каждый юзер сам (`/lastfm`). Для Spotify-треков нужен скробблинг Spotify → Last.fm.

### Яндекс Музыка

Без серверных ключей: каждый юзер берёт токен сам (`/yandex` подскажет).
Если API висит с серверного IP — `YANDEX_PROXY_URL=http://user:pass@host:port`.

## 4. `.env` (шаблон)

```bash
cp .env.example .env   # или ENV_PROD для CI-деплоя, см. п.7
```

```ini
BOT_TOKEN=...                                   # от BotFather
FERNET_KEY=...                                  # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
DATABASE_URL=postgresql+asyncpg://playmystation:playmystation@postgres:5432/playmystation
REDIS_URL=redis://redis:6379/0
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
SPOTIFY_REDIRECT_URI=https://<DOMAIN>/oauth/spotify/callback
LASTFM_API_KEY=...
YTM_OAUTH_CLIENT_ID=...                         # опционально (иначе заголовки)
YTM_OAUTH_CLIENT_SECRET=...
YANDEX_PROXY_URL=                               # опционально
AUDIO_CACHE_CHANNEL_ID=                         # опционально, см. п.6
SENTRY_DSN=                                     # опционально
LOG_FORMAT=text                                 # json — для Loki
WEB_HOST=0.0.0.0
WEB_PORT=8000
PUBLIC_BASE_URL=https://<DOMAIN>
WEBHOOK_URL=https://<DOMAIN>                    # без пути; без него — polling
WEBHOOK_SECRET=                                 # openssl rand -hex 32
WEBHOOK_PATH=/webhook
BACKUP_RETENTION_DAYS=7
```

## 5. Первый запуск

```bash
cd ~/playmystation
docker compose up -d --build
docker compose logs app | grep -iE "WEBHOOK mode|POLLING mode|migrations applied"
curl -s localhost:8000/ready        # {"ok":true,...}
```

- Без `WEBHOOK_URL` — polling (входящий HTTPS не нужен, Caddy всё равно поднимет серт).
- С `WEBHOOK_URL` — webhook-режим; проверка:
  `curl -s https://api.telegram.org/bot<TOKEN>/getWebhookInfo` → правильный `url`, `pending_update_count: 0`.
- В BotFather: `/setprivacy` → **Disable** (иначе в группах бот видит только команды/упоминания/реплаи), добавить бота в группу заново после смены.

## 6. Приватный канал для кеша аудио (опционально)

1. Создать приватный канал, добавить бота **админом**
2. Узнать ID (`@getmyid_bot`, вид `-100...`) → `AUDIO_CACHE_CHANNEL_ID`
3. Скачанное складывается в канал, повторы отдаются по `file_id` без перекачивания (Redis, 30 дней)

## 7. CI/CD через GitHub Actions (опционально)

Уже настроено (`.github/workflows/`): CI на каждый push, CD в `master` → SSH → pull → rebuild → healthcheck.

Секреты репозитория (Settings → Secrets → Actions):

| Секрет | Значение |
|---|---|
| `SSH_HOST` / `SSH_PORT` / `SSH_USER` | доступ к серверу |
| `SSH_PRIVATE_KEY` | приватный ключ (сгенерируй: `ssh-keygen -t ed25519 -f ~/.ssh/playmystation_deploy -N '""'`), публичный — в `~/.ssh/authorized_keys` сервера |
| `DOMAIN` | твой домен |
| `ENV_PROD` | прод-`.env` целиком (шаблон выше) |

Деплой ходит в Git по SSH: публичный ключ деплой-юзера → репозиторий → Settings → Deploy keys (✅ Allow write access).

## 8. Бэкапы и восстановление

Сервис `backup`: `pg_dump -Fc` ежедневно в 03:00 в volume `pgbackups` + при каждом старте. Проверка: `docker compose exec backup ls -la /backups`. Восстановление — командой из README (раздел «Бэкапы» в старом ридми убран сюда):

```bash
cd ~/playmystation
docker compose exec -T postgres pg_restore -U playmystation -d playmystation \
  --clean --if-exists < "$(docker compose exec backup ls -1 /backups/playmystation-*.dump | sort | tail -1 | tr -d '\r')"
```

Офсайт: `docker cp playmystation-backup-1:/backups ./pgbackups-$(date +%F)`.

## 9. Ротация Fernet-ключей

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# ENV: FERNET_KEY=<новый>, FERNET_KEYS_OLD=<старый> → деплой
docker compose exec app python -m app.core.security   # отчёт rotated/total
# убрать FERNET_KEYS_OLD → деплой
```

## 10. Мониторинг

- Prometheus → таргет `http://<host>:8000/metrics` (апдейты, провайдеры, кэш, breakers, HTTP, аудит)
- Sentry — через `SENTRY_DSN`; Loki — через `LOG_FORMAT=json`
- Живость: `docker compose ps`, `…/health`, `…/ready`

## 11. Эксплуатация: запреты и грабли

- **Никогда `docker compose down -v`**: сносит `pgdata` (все юзеры) и `caddy_data` (серты → rate limit Let's Encrypt).
- **Руками на сервере файлы не править** (был кейс с Caddyfile) — всё через git, иначе `git pull` встанет на конфликте.
- **Миграции всегда коммитить** (`alembic/versions/*.py`), иначе `relation "users" does not exist`.
- **`WEBHOOK_URL` — домен без пути** (`WEBHOOK_PATH` добавится сам; дубль `/webhook/webhook` даёт 404 на каждый апдейт).
- **Повторные тапы по кнопкам** дают `message is not modified` — глушится кодом (`app/bot/editing.py`), не трогать.

## 12. Troubleshooting

| Симптом | Причина → действие |
|---|---|
| `/now` молчит по Spotify, в логах `403 … owner of the app` | Нет Premium у владельца приложения → оформить, ждать часы |
| YouTube: пустая история при играющем треке | Привязка смотрит не в тот профиль / история приостановлена (`myactivity.google.com`) |
| yt-dlp `Sign in to confirm you're not a bot` | Куки протухли → перепривязать; дальше — Android/tv-клиенты и EJS уже в коде |
| yt-dlp `Signature solving failed` | Нет JS-рантайма: в образе node 22 + `yt-dlp-ejs` (проверить `node --version` в контейнере) |
| `Video unavailable` | Видео удалено/регион — не баг |
| `soundcloud`-ошибки в старых гайдах | Провайдер удалён (нужен Artist Pro), замена — YouTube Music |
| `message is not modified` + 500 | Старый код; обновиться (глушилка уже в `editing.py`) |
| OAuth Google `access_denied` | Не добавлен в Test users / не та почта на экране согласия |
| Токены OAuth отваливаются раз в ~7 дней | Testing-режим Google — норма, перепривязка |
| `network ... is ambiguous` | `docker network ls --filter name=playmystation -q \| xargs -r docker network rm` |
| `Bad Request: can't parse entities` | Неэкранированный HTML в тексте трека (`html.escape`) |
