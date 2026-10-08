import {serverOrigin, pairingCode, authHeaders, permissionPattern} from "./helpers.mjs";

let busy = false;
let uploadController;
const session = chrome.storage.session;
const status = text => session.set({status: text});

async function clearPending() {
  await session.remove("pending");
  await chrome.alarms.clear("pair-expiry");
}

chrome.action.onClicked.addListener(() => {
  chrome.tabs.create({url: chrome.runtime.getURL("connect.html")});
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  // No externally_connectable or content scripts: only our own UI can arm capture.
  if (sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL("connect.html")) {
    return false;
  }
  (async () => {
    if (message.type === "cancel") {
      uploadController?.abort();
      await clearPending();
      await status("Остановлено. Если передача уже завершилась, отключи сервис через /disconnect youtube.");
      return {ok: true};
    }
    if (message.type !== "connect" || busy) throw new Error("Подожди завершения текущего подключения.");
    const origin = serverOrigin(message.origin);
    const code = pairingCode(message.code);
    if (!(await chrome.permissions.contains({origins: [permissionPattern(origin)]}))) {
      throw new Error("Нет разрешения на подключение к выбранному серверу.");
    }
    await clearPending();
    // Create a blank tab first: never capture another tab/account by accident.
    const tab = await chrome.tabs.create({url: "about:blank"});
    await session.set({pending: {origin, code, tabId: tab.id, deadline: Date.now() + 600000}});
    await chrome.alarms.create("pair-expiry", {delayInMinutes: 10});
    await status("Ожидаю вход в YouTube Music. Открой «Библиотека» в новой вкладке, затем вернись сюда.");
    await chrome.tabs.update(tab.id, {url: "https://music.youtube.com/library"});
    return {ok: true};
  })().then(reply).catch(() => reply({ok: false, error: "Не удалось начать подключение. Проверь адрес и разрешения."}));
  return true;
});

chrome.alarms.onAlarm.addListener(async alarm => {
  if (alarm.name !== "pair-expiry") return;
  uploadController?.abort();
  await clearPending();
  await status("Время подключения истекло. Получи новый код командой /youtube_connect.");
});

chrome.tabs.onRemoved.addListener(async tabId => {
  const {pending} = await session.get("pending");
  if (pending?.tabId === tabId && !busy) {
    await clearPending();
    await status("Вкладка YouTube Music закрыта. Для новой попытки нажми «Подключить».");
  }
});

async function capture(details) {
  if (busy) return;
  busy = true;
  try {
    const {pending} = await session.get("pending");
    if (!pending || pending.tabId !== details.tabId || pending.deadline <= Date.now() ||
        details.initiator !== "https://music.youtube.com") return;
    const headers = await authHeaders(details.requestHeaders || []);
    if (!headers) return;
    const current = (await session.get("pending")).pending;
    // Cancellation or a new connection may have happened during the hash calculation.
    if (!current || current.code !== pending.code || current.tabId !== pending.tabId) return;
    // Remove the code before sending: no automatic retries or silent uploads.
    await clearPending();
    await status("Проверяю подключение…");
    uploadController = new AbortController();
    const timeout = setTimeout(() => uploadController?.abort(), 30000);
    try {
      const response = await fetch(pending.origin + "/connect/youtube", {
        method: "POST",
        headers: {"Content-Type": "application/json", Authorization: "Bearer " + pending.code},
        body: JSON.stringify({headers}),
        credentials: "omit",
        redirect: "error", // Never forward session credentials to a redirected host.
        signal: uploadController.signal
      });
      const data = response.ok ? await response.json() : null;
      if (data?.ok !== true) throw new Error("verification failed");
      await status("Подключено! Вернись в Telegram и отправь /youtube, затем /now.");
    } finally {
      clearTimeout(timeout);
      uploadController = undefined;
    }
  } catch {
    // Do not show/log response bodies or raw exceptions: they may contain credentials.
    await status("Не удалось подтвердить подключение. Проверь сервер и вход в YouTube Music, получи новый /youtube_connect и повтори.");
  } finally {
    busy = false;
  }
}

chrome.webRequest.onBeforeSendHeaders.addListener(
  details => { void capture(details); },
  {urls: ["https://music.youtube.com/youtubei/v1/*"], types: ["xmlhttprequest"]},
  ["requestHeaders", "extraHeaders"]
);
