with open("C:/Users/winged/Desktop/playmystation/app/bot/handlers/start.py", "r", encoding="utf-8") as f:
    content = f.read()

old = """# Подключаем
    if provider == "spotify":
        url = sp_auth_url(state=str(cb.from_user.id))
        await cb.message.edit_text(
            "🟢 <b>Подключение Spotify</b>\\nНажми кнопку и подтверди доступ.\\n\\n"
            "Если страница колбэка не откроется — скопируй параметр "
            "<code>code=...</code> из адресной строки и пришли командой "
            "<code>/spotify <код></code>.",
            reply_markup=connect_kb(provider, url),
        )
    elif provider == "soundcloud":
        if not settings.soundcloud_client_id:
            await cb.answer("SoundCloud OAuth не настроен (.env)", show_alert=True)
            return
        url = sc_auth_url(state=str(cb.from_user.id))
        await cb.message.edit_text(
            "🟠 <b>Подключение SoundCloud</b>\\nНажми кнопку и подтверди доступ.",
            reply_markup=connect_kb(provider, url),
        )
    elif provider == "yandex":
        await cb.message.edit_text(
            "🔴 <b>Подключение Яндекс Музыки</b>\\n\\n"
            "1. Открой ссылку и войди в свой Яндекс ID:\\n"
            "<code>https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d</code>\\n"
            "2. После входа тебя вернёт на music.yandex.ru — скопируй "
            "значение <code>access_token=...</code> из адресной строки\\n"
            "3. Пришли его боту командой:\\n"
            "<code>/yandex <токен></code>\\n\\n"
            "Токен хранится в зашифрованном виде и используется только для чтения очереди."
        )
    elif provider == "lastfm":
        await cb.message.edit_text(
            "🟪 <b>Подключение Last.fm</b>\\n\\n"
            "OAuth не нужен — просто пришли свой username:\\n"
            "<code>/lastfm <username></code>\\n\\n"
            "Чтобы бот видел треки из Spotify, свяжи Spotify → Last.fm "
            "(скробблинг) в настройках Last.fm. Работает и на free-аккаунтах."
        )
    await cb.answer()"""

new = """# Подключаем - используем edit_caption для фото, edit_text для текста
    async def _edit_msg(text: str, markup=None):
        if cb.message.photo:
            return await cb.message.edit_caption(text, reply_markup=markup)
        return await cb.message.edit_text(text, reply_markup=markup)

    if provider == "spotify":
        url = sp_auth_url(state=str(cb.from_user.id))
        await _edit_msg(
            "🟢 <b>Подключение Spotify</b>\\nНажми кнопку и подтверди доступ.\\n\\n"
            "Если страница колбэка не откроется — скопируй параметр "
            "<code>code=...</code> из адресной строки и пришли командой "
            "<code>/spotify <код></code>.",
            connect_kb(provider, url),
        )
    elif provider == "soundcloud":
        if not settings.soundcloud_client_id:
            await cb.answer("SoundCloud OAuth не настроен (.env)", show_alert=True)
            return
        url = sc_auth_url(state=str(cb.from_user.id))
        await _edit_msg(
            "🟠 <b>Подключение SoundCloud</b>\\nНажми кнопку и подтверди доступ.",
            connect_kb(provider, url),
        )
    elif provider == "yandex":
        await _edit_msg(
            "🔴 <b>Подключение Яндекс Музыки</b>\\n\\n"
            "1. Открой ссылку и войди в свой Яндекс ID:\\n"
            "<code>https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d</code>\\n"
            "2. После входа тебя вернёт на music.yandex.ru — скопируй "
            "значение <code>access_token=...</code> из адресной строки\\n"
            "3. Пришли его боту командой:\\n"
            "<code>/yandex <токен></code>\\n\\n"
            "Токен хранится в зашифрованном виде и используется только для чтения очереди."
        )
    elif provider == "lastfm":
        await _edit_msg(
            "🟪 <b>Подключение Last.fm</b>\\n\\n"
            "OAuth не нужен — просто пришли свой username:\\n"
            "<code>/lastfm <username></code>\\n\\n"
            "Чтобы бот видел треки из Spotify, свяжи Spotify → Last.fm "
            "(скробблинг) в настройках Last.fm. Работает и на free-аккаунтах."
        )
    await cb.answer()"""

if old in content:
    content = content.replace(old, new)
    with open("C:/Users/winged/Desktop/playmystation/app/bot/handlers/start.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed!")
else:
    print("NOT FOUND - trying regex...")
    import re
    pattern = re.compile(r'# Подключаем\n    if provider == "spotify":.*?await cb\.answer\(\)', re.DOTALL)
    if pattern.search(content):
        content = pattern.sub(new, content)
        with open("C:/Users/winged/Desktop/playmystation/app/bot/handlers/start.py", "w", encoding="utf-8") as f:
            f.write(content)
        print("Fixed with regex!")
    else:
        print("Pattern not found either")