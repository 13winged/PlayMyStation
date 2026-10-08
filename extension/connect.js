import {serverOrigin, pairingCode, permissionPattern} from "./helpers.mjs";

const form = document.querySelector("form");
const status = document.querySelector("#status");
const codeInput = document.querySelector("#code");
const submit = document.querySelector("button[type=submit]");

chrome.storage.session.get("status").then(data => {
  if (data.status) status.textContent = data.status;
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes.status?.newValue) status.textContent = changes.status.newValue;
});
form.addEventListener("submit", async event => {
  event.preventDefault();
  submit.disabled = true;
  try {
    const origin = serverOrigin(document.querySelector("#server").value);
    const code = pairingCode(codeInput.value);
    // Called directly from the user's click; only this host is requested.
    const allowed = await chrome.permissions.request({origins: [permissionPattern(origin)]});
    if (!allowed) throw new Error("Для передачи данных нужно разрешение на выбранный сервер.");
    const result = await chrome.runtime.sendMessage({type: "connect", origin, code});
    if (!result.ok) throw new Error(result.error);
    codeInput.value = "";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
document.querySelector("#cancel").addEventListener("click", async () => {
  codeInput.value = "";
  await chrome.runtime.sendMessage({type: "cancel"});
});
