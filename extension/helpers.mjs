export function serverOrigin(raw) {
  const url = new URL(raw.trim());
  const local = ["localhost", "127.0.0.1"].includes(url.hostname);
  if ((url.protocol !== "https:" && !(local && url.protocol === "http:")) ||
      url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("Укажи адрес HTTPS-сервера без пути. HTTP разрешён только для localhost.");
  }
  return url.origin;
}

export function pairingCode(raw) {
  const code = raw.trim();
  if (!/^[A-Za-z0-9_-]{32}$/.test(code)) throw new Error("Скопируй код из /youtube_connect целиком.");
  return code;
}

export function permissionPattern(origin) {
  const url = new URL(serverOrigin(origin));
  // Chrome host match patterns do not scope permissions to a TCP port.
  return `${url.protocol}//${url.hostname}/*`;
}

export async function authHeaders(requestHeaders, now = Date.now()) {
  const headers = Object.fromEntries(requestHeaders.map(h => [h.name.toLowerCase(), h.value]));
  const cookie = headers.cookie;
  if (!cookie) return null;
  const cookies = Object.fromEntries(cookie.split(";").map(part => {
    const i = part.indexOf("=");
    return [part.slice(0, i).trim(), part.slice(i + 1).trim()];
  }));
  if (!cookies["__Secure-3PAPISID"]) return null;
  // Chrome may hide Authorization from webRequest. Reconstruct SAPISIDHASH
  // using this request's session cookie; ytmusicapi refreshes it on later calls.
  const sid = cookies.SAPISID || cookies["__Secure-3PAPISID"];
  const timestamp = Math.floor(now / 1000);
  const input = `${timestamp} ${sid} https://music.youtube.com`;
  const digest = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(input));
  const hash = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
  const result = {
    cookie,
    authorization: `SAPISIDHASH ${timestamp}_${hash}`,
    "x-goog-authuser": headers["x-goog-authuser"] || "0"
  };
  if (headers["x-goog-pageid"]) result["x-goog-pageid"] = headers["x-goog-pageid"];
  return result;
}
