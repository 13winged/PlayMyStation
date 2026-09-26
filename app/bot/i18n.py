"""RU/EN локализация. Все пользовательские строки — здесь, с плейсхолдерами {x}.

Использование: `t(lang, "key", name=value)`. Неизвестный язык → fallback на RU,
отсутствующий ключ → KeyError на этапе разработки (тест на паритет).
Динамические значения экранирует вызывающий код (html.escape).
"""

from __future__ import annotations

from app.db.models import User

STRINGS: dict[str, dict[str, str]] = {
    "ru": {
        # /start, /services, /disconnect
        "start_text": (
            "👋 <b>PlayMyStation</b>\n\n"
            "Подключи до 4 аккаунтов: Spotify, Яндекс Музыку, YouTube Music и Last.fm.\n"
            "Выбери активный сервис или режим <b>ALL</b> — тогда /now найдёт тот, где музыка играет прямо сейчас.\n\n"
            "Команды:\n"
            "• /services — подключить / выбрать сервис\n"
            "• /now или /np — что сейчас играет (+ пришлю трек)\n"
            "• /spotify /yandex /youtube /lastfm — выбрать сервис (или подключить)\n"
            "• /lang — язык (RU/EN)\n"
            "• /disconnect &lt;provider&gt; — отключить сервис"
        ),
        "services_text": (
            "⚙️ <b>Мои сервисы</b>\nНажми на сервис, чтобы подключить / отключить. "
            "Второй ряд — выбор активного для /now."
        ),
        "services_title": "⚙️ <b>Мои сервисы</b>",
        "disconnect_usage": (
            "❌ Укажи провайдера: <code>/disconnect {example}</code>\n"
            "Доступные: {available}"
        ),
        "disconnect_not_bound": "ℹ️ {provider} не был подключен.",
        "disconnect_done": "✅ {provider} отключён.",
        "set_active_answer": "Активный сервис: {provider}",
        "toggle_off_answer": "{provider} отключён",
        # Подключение Spotify
        "sp_connect": (
            "🟢 <b>Подключение Spotify</b>\nНажми кнопку и подтверди доступ.\n\n"
            "Если страница колбэка не откроется — скопируй параметр "
            "<code>code=...</code> из адресной строки и пришли командой "
            "<code>/spotify &lt;код&gt;</code>."
        ),
        "sp_hint": (
            "🟢 Пришли код так:\n<code>/spotify &lt;код_из_адресной_строки&gt;</code>\n\n"
            "Где взять код:\n"
            "1. Нажми ➕ Spotify в /services и подтверди доступ\n"
            "2. Браузер перейдёт на страницу колбэка (она может не открыться — это ОК)\n"
            "3. Скопируй значение параметра <code>code=...</code> из адресной строки\n"
            "4. Пришли его этой командой (код одноразовый, живёт ~10 минут)"
        ),
        "sp_no_code": "❌ Не нашёл код. Пришли <code>/spotify &lt;код&gt;</code>.",
        "sp_wrong_state": (
            "❌ Этот код выдан для другого Telegram-аккаунта "
            "(state={state}).\nПройди авторизацию заново с этого аккаунта."
        ),
        "sp_no_oauth": "❌ Spotify OAuth не настроен на сервере (.env).",
        "sp_rejected": (
            "❌ Spotify отклонил код.\n"
            "Причина: <code>{reason}</code>\n\n"
            "Чаще всего это несовпадение redirect_uri: в обмене должен быть "
            "точно тот же URI, что в ссылке авторизации. Проверь "
            "SPOTIFY_REDIRECT_URI в настройках сервера."
        ),
        "sp_ok": "✅ Spotify подключён! Жми /now 🎵",
        "sp_active": "🟢 Активный сервис: <b>Spotify</b>. Жми /now 🎵",
        # Подключение Яндекс Музыки
        "yx_connect": (
            "🔴 <b>Подключение Яндекс Музыки</b>\n\n"
            "1. Открой ссылку и войди в свой Яндекс ID:\n"
            "<code>https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d</code>\n"
            "2. После входа тебя вернёт на music.yandex.ru — скопируй "
            "значение <code>access_token=...</code> из адресной строки\n"
            "3. Пришли его боту командой:\n"
            "<code>/yandex &lt;токен&gt;</code>\n\n"
            "Токен хранится в зашифрованном виде и используется только для чтения очереди."
        ),
        "yx_hint": "🔴 Пришли токен так:\n<code>/yandex &lt;твой_токен&gt;</code>",
        "yx_invalid": "❌ Токен не подошёл. Проверь и попробуй ещё раз.",
        "yx_ok": "✅ Яндекс Музыка подключена{hint}. Активный сервис: {active}.",
        "yx_empty_queue_hint": " (очередь пуста — запусти трек и проверь /now)",
        "yx_active": "🔴 Активный сервис: <b>Яндекс Музыка</b>. Жми /now 🎵",
        # Подключение YouTube Music
        "yt_connect": (
            "▶️ <b>Подключение YouTube Music</b>\n\n"
            "1. Открой <code>music.youtube.com</code> в браузере и войди в аккаунт\n"
            "2. Открой DevTools (Ctrl+Shift+I) → Network, в фильтр введи "
            "<code>/browse</code>\n"
            "3. Обнови страницу, найди POST-запрос <code>browse?...</code> и скопируй "
            "заголовки ЦЕЛИКОМ (включая <code>authorization:</code>, "
            "<code>cookie:</code> и <code>x-goog-authuser:</code>)\n"
            "4. Пришли их боту командой:\n"
            "<code>/youtube &lt;заголовки&gt;</code>"
        ),
        "yt_hint": (
            "▶️ <b>Подключение YouTube Music</b>\n\n"
            "1. Открой <code>music.youtube.com</code> в браузере и войди в аккаунт\n"
            "2. Открой DevTools (Ctrl+Shift+I) → вкладка Network, в фильтр введи "
            "<code>/browse</code>\n"
            "3. Обнови страницу (Ctrl+R), найди POST-запрос <code>browse?...</code>\n"
            "4. Скопируй заголовки ЦЕЛИКОМ (Firefox: правый клик → Copy → "
            "Copy Request Headers). Нужны в том числе строки "
            "<code>authorization: SAPISIDHASH...</code>, <code>cookie: ...</code> "
            "и <code>x-goog-authuser: ...</code> — по двум строкам не взлетит\n"
            "5. Пришли их боту одним сообщением:\n"
            "<code>/youtube &lt;заголовки&gt;</code>\n\n"
            "Заголовки хранятся в зашифрованном виде и действуют, пока жива сессия "
            "в браузере (обычно ~2 года)."
        ),
        "yt_incomplete": (
            "❌ Заголовки неполные: нужны ВСЕ заголовки запроса "
            "<code>/browse</code> целиком (включая "
            "<code>authorization: SAPISIDHASH...</code>). "
            "В DevTools: правый клик по запросу → Copy → "
            "Copy Request Headers → вставь всё как есть."
        ),
        "yt_not_logged_in": (
            "❌ В cookie нет признака входа в аккаунт "
            "(__Secure-3PAPISID). Ты скопировал заголовки из "
            "незалогиненной сессии: войди на music.youtube.com "
            "(аватар справа вверху, не кнопка «Войти»), обнови страницу "
            "и скопируй заголовки заново."
        ),
        "yt_check_failed": (
            "❌ Заголовки не подошли (история не открылась). "
            "Скопируй свежие заголовки и попробуй ещё раз."
        ),
        "yt_ok": "✅ YouTube Music подключён! Жми /now 🎵",
        "yt_active": "▶️ Активный сервис: <b>YouTube Music</b>. Жми /now 🎵",
        # Подключение Last.fm
        "lfm_connect": (
            "🟪 <b>Подключение Last.fm</b>\n\n"
            "OAuth не нужен — просто пришли свой username:\n"
            "<code>/lastfm &lt;username&gt;</code>\n\n"
            "Чтобы бот видел треки из Spotify, свяжи Spotify → Last.fm "
            "(скробблинг) в настройках Last.fm. Работает и на free-аккаунтах."
        ),
        "lfm_hint": (
            "🟪 Пришли username так:\n<code>/lastfm &lt;твой_lastfm_username&gt;</code>\n\n"
            "Где взять: Paper Planes → Last.fm → Settings → профиль. "
            "Плюс свяжи Spotify → Last.fm (скробблинг), чтобы бот видел треки."
        ),
        "lfm_no_key": "❌ Last.fm API-ключ не настроен на сервере (.env).",
        "lfm_no_network": "❌ Last.fm не отвечает. Попробуй позже.",
        "lfm_not_found": (
            "❌ Пользователь <code>{username}</code> "
            "не найден на Last.fm. Проверь username."
        ),
        "lfm_ok": "✅ Last.fm подключён (<code>{username}</code>). Жми /now 🎵",
        "lfm_active": "🟪 Активный сервис: <b>Last.fm</b>. Жми /now 🎵",
        # /now
        "now_no_services": (
            "❌ Нет привязанных сервисов.\nОткрой /services и подключи хотя бы один."
        ),
        "now_nothing": (
            "⏸️ Сейчас ничего не играет (или API не вернуло трек).\n"
            "Проверь, что музыка запущена, или смени активный сервис в /services."
        ),
        "now_nothing_short": "⏸️ Сейчас ничего не играет.",
        "preview_unavailable": (
            "ℹ️ Превью недоступно для этого трека.\n"
            "Spotify отдаёт превью не для всех треков."
        ),
        "preview_failed": "❌ Не получилось скачать превью. Попробуй позже.",
        # /lang
        "lang_current": "🌐 Текущий язык: <b>{language}</b>. Выбери новый:",
        "lang_set": "✅ Язык: <b>{language}</b>.",
        "lang_name_ru": "Русский",
        "lang_name_en": "English",
        # Карточка трека
        "card_playing": "▶️ Сейчас играет",
        "card_paused": "⏸️ Последний трек",
        "provider_spotify": "Spotify",
        "provider_yandex": "Яндекс Музыка",
        "provider_youtube": "YouTube Music",
        "provider_lastfm": "Last.fm",
        "card_open_track": "Открыть трек",
        "card_yt_note": (
            "ℹ️ YouTube Music не отдаёт realtime-статус — показан последний трек из истории."
        ),
        # Кнопки
        "btn_services": "⚙️ Мои сервисы",
        "btn_now": "🎵 Сейчас играет (/now)",
        "btn_preview": "⏬ Превью (30 сек)",
        "btn_connect": "🔗 Подключить",
        "btn_back": "◀️ Назад к сервисам",
        # Кнопки управления Spotify
        "btn_pause": "⏸ Пауза",
        "btn_play": "▶️ Играть",
        "btn_next": "⏭ Дальше",
        "btn_prev": "⏮ Назад",
        "btn_like": "❤️ В любимые",
        "ctl_paused": "⏸ Пауза",
        "ctl_resumed": "▶️ Играет",
        "ctl_skipped_next": "⏭ Следующий трек",
        "ctl_skipped_prev": "⏮ Предыдущий трек",
        "ctl_liked": "❤️ В любимых",
        "ctl_failed": (
            "❌ Не вышло: нужны Spotify Premium, активное устройство "
            "и свежая привязка (переподключи Spotify в /services)."
        ),
        "ctl_no_spotify": "❌ Spotify не подключён. Открой /services.",
    },
    "en": {
        "start_text": (
            "👋 <b>PlayMyStation</b>\n\n"
            "Connect up to 4 accounts: Spotify, Yandex Music, YouTube Music and Last.fm.\n"
            "Pick an active service or <b>ALL</b> mode — then /now finds where music is playing right now.\n\n"
            "Commands:\n"
            "• /services — connect / pick a service\n"
            "• /now or /np — what's playing now (+ I'll send the track)\n"
            "• /spotify /yandex /youtube /lastfm — select a service (or connect it)\n"
            "• /lang — language (RU/EN)\n"
            "• /disconnect &lt;provider&gt; — disconnect a service"
        ),
        "services_text": (
            "⚙️ <b>My services</b>\nTap a service to connect / disconnect. "
            "Second row picks the active one for /now."
        ),
        "services_title": "⚙️ <b>My services</b>",
        "disconnect_usage": (
            "❌ Specify a provider: <code>/disconnect {example}</code>\n"
            "Available: {available}"
        ),
        "disconnect_not_bound": "ℹ️ {provider} was not connected.",
        "disconnect_done": "✅ {provider} disconnected.",
        "set_active_answer": "Active service: {provider}",
        "toggle_off_answer": "{provider} disconnected",
        "sp_connect": (
            "🟢 <b>Connecting Spotify</b>\nTap the button and approve access.\n\n"
            "If the callback page doesn't open — copy the "
            "<code>code=...</code> parameter from the address bar and send it with "
            "<code>/spotify &lt;code&gt;</code>."
        ),
        "sp_hint": (
            "🟢 Send the code like this:\n<code>/spotify &lt;code_from_address_bar&gt;</code>\n\n"
            "Where to get it:\n"
            "1. Tap ➕ Spotify in /services and approve access\n"
            "2. The browser will go to the callback page (it may fail to open — that's OK)\n"
            "3. Copy the <code>code=...</code> parameter from the address bar\n"
            "4. Send it with this command (single-use, lives ~10 minutes)"
        ),
        "sp_no_code": "❌ Code not found. Send <code>/spotify &lt;code&gt;</code>.",
        "sp_wrong_state": (
            "❌ This code was issued for another Telegram account "
            "(state={state}).\nAuthorize again from this account."
        ),
        "sp_no_oauth": "❌ Spotify OAuth is not configured on the server (.env).",
        "sp_rejected": (
            "❌ Spotify rejected the code.\n"
            "Reason: <code>{reason}</code>\n\n"
            "Usually it's a redirect_uri mismatch: the exchange must use "
            "exactly the same URI as the authorize link. Check "
            "SPOTIFY_REDIRECT_URI on the server."
        ),
        "sp_ok": "✅ Spotify connected! Hit /now 🎵",
        "sp_active": "🟢 Active service: <b>Spotify</b>. Hit /now 🎵",
        "yx_connect": (
            "🔴 <b>Connecting Yandex Music</b>\n\n"
            "1. Open the link and sign in with your Yandex ID:\n"
            "<code>https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d</code>\n"
            "2. You'll land on music.yandex.ru — copy the "
            "<code>access_token=...</code> value from the address bar\n"
            "3. Send it to the bot:\n"
            "<code>/yandex &lt;token&gt;</code>\n\n"
            "The token is stored encrypted and only used to read the queue."
        ),
        "yx_hint": "🔴 Send the token like this:\n<code>/yandex &lt;your_token&gt;</code>",
        "yx_invalid": "❌ This token didn't work. Check it and try again.",
        "yx_ok": "✅ Yandex Music connected{hint}. Active service: {active}.",
        "yx_empty_queue_hint": " (queue is empty — play a track and check /now)",
        "yx_active": "🔴 Active service: <b>Yandex Music</b>. Hit /now 🎵",
        "yt_connect": (
            "▶️ <b>Connecting YouTube Music</b>\n\n"
            "1. Open <code>music.youtube.com</code> in your browser and sign in\n"
            "2. Open DevTools (Ctrl+Shift+I) → Network, filter by "
            "<code>/browse</code>\n"
            "3. Reload the page, find the POST <code>browse?...</code> request and copy "
            "the headers IN FULL (including <code>authorization:</code>, "
            "<code>cookie:</code> and <code>x-goog-authuser:</code>)\n"
            "4. Send them to the bot:\n"
            "<code>/youtube &lt;headers&gt;</code>"
        ),
        "yt_hint": (
            "▶️ <b>Connecting YouTube Music</b>\n\n"
            "1. Open <code>music.youtube.com</code> in your browser and sign in\n"
            "2. Open DevTools (Ctrl+Shift+I) → Network tab, filter by "
            "<code>/browse</code>\n"
            "3. Reload the page (Ctrl+R), find the POST <code>browse?...</code> request\n"
            "4. Copy the headers IN FULL (Firefox: right click → Copy → "
            "Copy Request Headers). You need the "
            "<code>authorization: SAPISIDHASH...</code>, <code>cookie: ...</code> "
            "and <code>x-goog-authuser: ...</code> lines — two lines won't work\n"
            "5. Send them to the bot in one message:\n"
            "<code>/youtube &lt;headers&gt;</code>\n\n"
            "Headers are stored encrypted and live as long as your browser "
            "session (usually ~2 years)."
        ),
        "yt_incomplete": (
            "❌ Incomplete headers: I need ALL headers of the "
            "<code>/browse</code> request (including "
            "<code>authorization: SAPISIDHASH...</code>). "
            "In DevTools: right click the request → Copy → "
            "Copy Request Headers → paste everything as is."
        ),
        "yt_not_logged_in": (
            "❌ The cookie shows no signed-in account "
            "(__Secure-3PAPISID). You copied headers from a "
            "signed-out session: sign in on music.youtube.com "
            "(avatar top right, not a «Sign in» button), reload the page "
            "and copy the headers again."
        ),
        "yt_check_failed": (
            "❌ These headers didn't work (history won't open). "
            "Copy fresh headers and try again."
        ),
        "yt_ok": "✅ YouTube Music connected! Hit /now 🎵",
        "yt_active": "▶️ Active service: <b>YouTube Music</b>. Hit /now 🎵",
        "lfm_connect": (
            "🟪 <b>Connecting Last.fm</b>\n\n"
            "No OAuth needed — just send your username:\n"
            "<code>/lastfm &lt;username&gt;</code>\n\n"
            "To let the bot see Spotify tracks, link Spotify → Last.fm "
            "(scrobbling) in Last.fm settings. Works for free accounts too."
        ),
        "lfm_hint": (
            "🟪 Send your username like this:\n<code>/lastfm &lt;your_lastfm_username&gt;</code>\n\n"
            "Where to find it: Last.fm → Settings → profile. "
            "Plus link Spotify → Last.fm (scrobbling) so the bot sees tracks."
        ),
        "lfm_no_key": "❌ Last.fm API key is not configured on the server (.env).",
        "lfm_no_network": "❌ Last.fm is not responding. Try later.",
        "lfm_not_found": (
            "❌ User <code>{username}</code> "
            "not found on Last.fm. Check the username."
        ),
        "lfm_ok": "✅ Last.fm connected (<code>{username}</code>). Hit /now 🎵",
        "lfm_active": "🟪 Active service: <b>Last.fm</b>. Hit /now 🎵",
        "now_no_services": (
            "❌ No connected services.\nOpen /services and connect at least one."
        ),
        "now_nothing": (
            "⏸️ Nothing is playing right now (or the API returned no track).\n"
            "Check that music is playing, or switch the active service in /services."
        ),
        "now_nothing_short": "⏸️ Nothing is playing right now.",
        "preview_unavailable": (
            "ℹ️ Preview is unavailable for this track.\n"
            "Spotify doesn't provide previews for every track."
        ),
        "preview_failed": "❌ Couldn't download the preview. Try later.",
        "lang_current": "🌐 Current language: <b>{language}</b>. Pick a new one:",
        "lang_set": "✅ Language: <b>{language}</b>.",
        "lang_name_ru": "Русский",
        "lang_name_en": "English",
        "card_playing": "▶️ Now playing",
        "card_paused": "⏸️ Last track",
        "provider_spotify": "Spotify",
        "provider_yandex": "Yandex Music",
        "provider_youtube": "YouTube Music",
        "provider_lastfm": "Last.fm",
        "card_open_track": "Open track",
        "card_yt_note": (
            "ℹ️ YouTube Music has no realtime status — showing the latest history track."
        ),
        "btn_services": "⚙️ My services",
        "btn_now": "🎵 Now playing (/now)",
        "btn_preview": "⏬ Preview (30 sec)",
        "btn_connect": "🔗 Connect",
        "btn_back": "◀️ Back to services",
        "btn_pause": "⏸ Pause",
        "btn_play": "▶️ Play",
        "btn_next": "⏭ Next",
        "btn_prev": "⏮ Previous",
        "btn_like": "❤️ Like",
        "ctl_paused": "⏸ Paused",
        "ctl_resumed": "▶️ Playing",
        "ctl_skipped_next": "⏭ Next track",
        "ctl_skipped_prev": "⏮ Previous track",
        "ctl_liked": "❤️ Liked",
        "ctl_failed": (
            "❌ Failed: Spotify Premium, an active device "
            "and a fresh link are required (reconnect Spotify in /services)."
        ),
        "ctl_no_spotify": "❌ Spotify is not connected. Open /services.",
    },
}


def lang_of(user: User | None) -> str:
    """Язык юзера с фолбэком на RU."""
    lang = (user.language if user is not None else "") or "ru"
    return lang if lang in STRINGS else "ru"


def t(lang: str, key: str, **kwargs: object) -> str:
    """Взять строку и подставить плейсхолдеры."""
    template = STRINGS.get(lang, STRINGS["ru"])[key]
    return template.format(**kwargs) if kwargs else template
